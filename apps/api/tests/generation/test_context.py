from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.analysis.viral_models import (
    ViralCandidate,
    ViralCandidateStatus,
    ViralCategory,
    ViralLibraryItem,
)
from app.modules.content.account_models import (
    ColumnCampaign,
    ColumnCampaignKind,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import Content, ContentStatus
from app.modules.generation.context import GenerationContextBuilder
from app.modules.generation.schemas import (
    GenerationInputs,
    StyleInheritanceSelection,
)
from app.modules.metrics.models import ContentType
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
    FactSourceKind,
    FactSourceLevel,
    FactSourceStatus,
)
from app.modules.style_facts.style_models import (
    AccountStyleProfile,
    StyleProfileStatus,
)
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


@dataclass
class ContextFixture:
    workspace_id: UUID
    member_id: UUID
    account_id: UUID
    column_id: UUID
    fact_item_id: UUID
    style_profile_id: UUID
    source_asset_id: UUID
    model_config_id: UUID
    eligible_viral_ids: tuple[UUID, ...]
    eligible_candidate_ids: tuple[UUID, ...]
    other_account_viral_id: UUID
    other_platform_viral_id: UUID
    other_workspace_viral_id: UUID
    revoked_viral_id: UUID
    unconfirmed_candidate_id: UUID


def _content(
    *,
    workspace_id: UUID,
    account: PlatformAccount,
    title: str,
) -> Content:
    return Content(
        workspace_id=workspace_id,
        account_id=account.id,
        platform=account.platform,
        title=title,
        body=f"{title} 正文",
        objective_profile_id=uuid4(),
        benchmark_profile_id=uuid4(),
        content_type=ContentType.VIDEO,
        status=ContentStatus.PUBLISHED,
        published_title=title,
        published_body=f"{title} 已发布正文",
    )


def _library_item(
    *,
    workspace_id: UUID,
    account_id: UUID,
    content_id: UUID,
    member_id: UUID,
    candidate_id: UUID,
    label: str,
    revoked: bool = False,
) -> ViralLibraryItem:
    return ViralLibraryItem(
        workspace_id=workspace_id,
        account_id=account_id,
        candidate_id=candidate_id,
        content_id=content_id,
        category=ViralCategory.ENGAGEMENT,
        strategy_tags=[f"{label}-钩子"],
        applicable_scenarios=[f"{label}-场景"],
        structure_summary=f"{label}-结构",
        confirmed_by=member_id,
        revoked_by=member_id if revoked else None,
        revoked_at=datetime(2026, 7, 23, tzinfo=UTC) if revoked else None,
        revocation_reason="不再适用" if revoked else None,
    )


def _candidate(
    *,
    workspace_id: UUID,
    account: PlatformAccount,
    content_id: UUID,
    status: ViralCandidateStatus,
) -> ViralCandidate:
    return ViralCandidate(
        workspace_id=workspace_id,
        account_id=account.id,
        content_id=content_id,
        snapshot_id=uuid4(),
        platform=account.platform,
        content_type=ContentType.VIDEO,
        maturity_bucket="24h",
        category=ViralCategory.ENGAGEMENT,
        metric_key="engagement_rate",
        actual_value=Decimal("0.2"),
        percentile=0.95,
        sample_count=30,
        threshold_value=Decimal("0.1"),
        threshold_profile_id=uuid4(),
        threshold_profile_version=1,
        objective_profile_id=uuid4(),
        benchmark_profile_id=uuid4(),
        evidence={},
        reason="合成候选",
        status=status,
    )


def _seed(session: Session) -> ContextFixture:
    workspace = Workspace(name="生成上下文工作区")
    other_workspace = Workspace(name="其他工作区")
    session.add_all([workspace, other_workspace])
    session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="生成编辑",
        role=MemberRole.EDITOR,
    )
    other_member = WorkspaceMember(
        workspace_id=other_workspace.id,
        display_name="其他编辑",
        role=MemberRole.EDITOR,
    )
    session.add_all([member, other_member])
    session.flush()
    account = PlatformAccount(
        workspace_id=workspace.id,
        platform=Platform.DOUYIN,
        name="主账号",
    )
    other_account = PlatformAccount(
        workspace_id=workspace.id,
        platform=Platform.DOUYIN,
        name="同平台其他账号",
    )
    other_platform_account = PlatformAccount(
        workspace_id=workspace.id,
        platform=Platform.XIAOHONGSHU,
        name="其他平台账号",
    )
    other_workspace_account = PlatformAccount(
        workspace_id=other_workspace.id,
        platform=Platform.DOUYIN,
        name="其他工作区账号",
    )
    session.add_all(
        [
            account,
            other_account,
            other_platform_account,
            other_workspace_account,
        ]
    )
    session.flush()
    column = ColumnCampaign(
        workspace_id=workspace.id,
        account_id=account.id,
        name="新品栏目",
        kind=ColumnCampaignKind.COLUMN,
    )
    session.add(column)

    contents = [
        _content(workspace_id=workspace.id, account=account, title=f"爆款 {index}")
        for index in range(1, 5)
    ]
    other_account_content = _content(
        workspace_id=workspace.id,
        account=other_account,
        title="其他账号爆款",
    )
    other_platform_content = _content(
        workspace_id=workspace.id,
        account=other_platform_account,
        title="其他平台爆款",
    )
    other_workspace_content = _content(
        workspace_id=other_workspace.id,
        account=other_workspace_account,
        title="其他工作区爆款",
    )
    session.add_all(
        [
            *contents,
            other_account_content,
            other_platform_content,
            other_workspace_content,
        ]
    )
    session.flush()
    eligible_candidates = tuple(
        _candidate(
            workspace_id=workspace.id,
            account=account,
            content_id=content.id,
            status=ViralCandidateStatus.CONFIRMED,
        )
        for content in contents[:3]
    )
    revoked_candidate = _candidate(
        workspace_id=workspace.id,
        account=account,
        content_id=contents[3].id,
        status=ViralCandidateStatus.REVOKED,
    )
    other_account_candidate = _candidate(
        workspace_id=workspace.id,
        account=other_account,
        content_id=other_account_content.id,
        status=ViralCandidateStatus.CONFIRMED,
    )
    other_platform_candidate = _candidate(
        workspace_id=workspace.id,
        account=other_platform_account,
        content_id=other_platform_content.id,
        status=ViralCandidateStatus.CONFIRMED,
    )
    other_workspace_candidate = _candidate(
        workspace_id=other_workspace.id,
        account=other_workspace_account,
        content_id=other_workspace_content.id,
        status=ViralCandidateStatus.CONFIRMED,
    )
    unconfirmed_candidate = _candidate(
        workspace_id=workspace.id,
        account=account,
        content_id=contents[3].id,
        status=ViralCandidateStatus.RECOMMENDED,
    )
    session.add_all(
        [
            *eligible_candidates,
            revoked_candidate,
            other_account_candidate,
            other_platform_candidate,
            other_workspace_candidate,
            unconfirmed_candidate,
        ]
    )
    session.flush()
    eligible = tuple(
        _library_item(
            workspace_id=workspace.id,
            account_id=account.id,
            content_id=content.id,
            member_id=member.id,
            candidate_id=candidate.id,
            label=f"爆款{index}",
        )
        for index, (content, candidate) in enumerate(
            zip(contents[:3], eligible_candidates, strict=True),
            start=1,
        )
    )
    revoked = _library_item(
        workspace_id=workspace.id,
        account_id=account.id,
        content_id=contents[3].id,
        member_id=member.id,
        candidate_id=revoked_candidate.id,
        label="已撤销",
        revoked=True,
    )
    other_account_item = _library_item(
        workspace_id=workspace.id,
        account_id=other_account.id,
        content_id=other_account_content.id,
        member_id=member.id,
        candidate_id=other_account_candidate.id,
        label="其他账号",
    )
    other_platform_item = _library_item(
        workspace_id=workspace.id,
        account_id=other_platform_account.id,
        content_id=other_platform_content.id,
        member_id=member.id,
        candidate_id=other_platform_candidate.id,
        label="其他平台",
    )
    other_workspace_item = _library_item(
        workspace_id=other_workspace.id,
        account_id=other_workspace_account.id,
        content_id=other_workspace_content.id,
        member_id=other_member.id,
        candidate_id=other_workspace_candidate.id,
        label="其他工作区",
    )
    session.add_all(
        [
            *eligible,
            revoked,
            other_account_item,
            other_platform_item,
            other_workspace_item,
        ]
    )

    fact_source = FactSource(
        workspace_id=workspace.id,
        kind=FactSourceKind.TEXT,
        level=FactSourceLevel.L1,
        title="已确认商品资料",
        status=FactSourceStatus.PARSED,
        created_by=member.id,
        content_sha256="a" * 64,
    )
    session.add(fact_source)
    session.flush()
    fact_item = FactItem(
        workspace_id=workspace.id,
        source_id=fact_source.id,
        field_name="价格",
        field_code="price",
        value="299 元",
        source_location="line 1",
        confidence=1,
        status=FactItemStatus.CONFIRMED,
        conflict_status=FactConflictStatus.CLEAR,
        confirmed_by=member.id,
        confirmed_at=datetime(2026, 7, 23, tzinfo=UTC),
    )
    style_profile = AccountStyleProfile(
        workspace_id=workspace.id,
        account_id=account.id,
        scope_key="account",
        version=3,
        status=StyleProfileStatus.CONFIRMED,
        style={
            "title": {"hooks": ["结论前置"]},
            "copy": {"tones": ["克制"]},
            "cover": {"colors": ["深蓝"]},
            "prohibited": {
                "expressions": ["绝对化"],
                "colors": ["荧光色"],
                "layouts": ["拥挤"],
                "visual_styles": ["廉价感"],
            },
        },
        sample_content_ids=[],
        diff={},
        confirmed_by=member.id,
        confirmed_at=datetime(2026, 7, 23, tzinfo=UTC),
    )
    model_config = ModelConfig(
        workspace_id=workspace.id,
        provider="mock",
        model_id="mock-v1",
        capabilities=["text", "image"],
        status=ModelConfigStatus.VERIFIED,
        encrypted_api_key="encrypted-test-placeholder",
    )
    session.add_all([fact_item, style_profile, model_config])
    session.commit()

    return ContextFixture(
        workspace_id=workspace.id,
        member_id=member.id,
        account_id=account.id,
        column_id=column.id,
        fact_item_id=fact_item.id,
        style_profile_id=style_profile.id,
        source_asset_id=fact_source.id,
        model_config_id=model_config.id,
        eligible_viral_ids=tuple(item.id for item in eligible),
        eligible_candidate_ids=tuple(
            candidate.id for candidate in eligible_candidates
        ),
        other_account_viral_id=other_account_item.id,
        other_platform_viral_id=other_platform_item.id,
        other_workspace_viral_id=other_workspace_item.id,
        revoked_viral_id=revoked.id,
        unconfirmed_candidate_id=unconfirmed_candidate.id,
    )


def _builder(session: Session, fixture: ContextFixture) -> GenerationContextBuilder:
    return GenerationContextBuilder(
        session,
        WorkspaceContext(
            workspace_id=fixture.workspace_id,
            member_id=fixture.member_id,
            role="editor",
        ),
    )


def _inputs(
    fixture: ContextFixture,
    *,
    viral_ids: tuple[UUID, ...] | None = None,
    prompt: str = "突出通勤场景",
) -> GenerationInputs:
    return GenerationInputs(
        account_id=fixture.account_id,
        platform=Platform.DOUYIN,
        column_campaign_id=fixture.column_id,
        target="提升互动",
        confirmed_fact_item_ids=(fixture.fact_item_id,),
        style_profile_id=fixture.style_profile_id,
        style_switches=StyleInheritanceSelection(),
        viral_library_item_ids=(
            fixture.eligible_viral_ids if viral_ids is None else viral_ids
        ),
        user_prompt=prompt,
        source_asset_ids=(fixture.source_asset_id,),
        risk_rule_version="douyin-risk-2026-07",
        model_config_id=fixture.model_config_id,
    )


def test_selects_zero_to_three_confirmed_viral_references_in_input_order() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        builder = _builder(session, fixture)

        empty = builder.create_run(_inputs(fixture, viral_ids=()))
        selected = builder.create_run(_inputs(fixture))

        assert empty.context.viral_references == ()
        assert tuple(
            reference.library_item_id
            for reference in selected.context.viral_references
        ) == fixture.eligible_viral_ids
        assert selected.context.viral_references[0].strategy_tags == (
            "爆款1-钩子",
        )

        with pytest.raises(ValueError, match="at most 3"):
            builder.create_run(
                _inputs(
                    fixture,
                    viral_ids=(
                        *fixture.eligible_viral_ids,
                        fixture.revoked_viral_id,
                    ),
                )
            )
        with pytest.raises(ValueError, match="unique"):
            builder.create_run(
                _inputs(
                    fixture,
                    viral_ids=(
                        fixture.eligible_viral_ids[0],
                        fixture.eligible_viral_ids[0],
                    ),
                )
            )


@pytest.mark.parametrize(
    "fixture_field",
    [
        "other_account_viral_id",
        "other_platform_viral_id",
        "other_workspace_viral_id",
        "revoked_viral_id",
        "unconfirmed_candidate_id",
    ],
)
def test_rejects_viral_references_outside_the_confirmed_generation_scope(
    fixture_field: str,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)

        with pytest.raises(ValueError, match="eligible"):
            _builder(session, fixture).create_run(
                _inputs(
                    fixture,
                    viral_ids=(getattr(fixture, fixture_field),),
                )
            )


def test_rejects_library_item_when_its_candidate_is_no_longer_confirmed() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        candidate = session.get(
            ViralCandidate,
            fixture.eligible_candidate_ids[0],
        )
        assert candidate is not None
        candidate.status = ViralCandidateStatus.RECOMMENDED
        session.flush()

        with pytest.raises(ValueError, match="viral reference.*eligible"):
            _builder(session, fixture).create_run(
                _inputs(
                    fixture,
                    viral_ids=(fixture.eligible_viral_ids[0],),
                )
            )


def test_context_snapshots_every_input_and_is_deeply_immutable() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        run = _builder(session, fixture).create_run(_inputs(fixture))
        context = run.context

        assert context.workspace_id == fixture.workspace_id
        assert context.account_id == fixture.account_id
        assert context.platform is Platform.DOUYIN
        assert context.column_campaign_id == fixture.column_id
        assert context.target == "提升互动"
        assert context.confirmed_facts[0].field_code == "price"
        assert context.confirmed_facts[0].value == "299 元"
        assert len(context.confirmed_facts_version) == 64
        assert context.style.profile_id == fixture.style_profile_id
        assert context.style.version == 3
        assert context.style.switches.title is True
        assert '"结论前置"' in context.style.style_json
        assert context.user_prompt == "突出通勤场景"
        assert context.source_assets[0].source_id == fixture.source_asset_id
        assert context.source_assets[0].content_sha256 == "a" * 64
        assert context.risk_rule_version == "douyin-risk-2026-07"
        assert context.model.config_id == fixture.model_config_id
        assert context.model.provider == "mock"
        assert context.model.capabilities == ("image", "text")
        assert "encrypted" not in context.model.model_dump_json()

        with pytest.raises(ValidationError):
            context.user_prompt = "尝试篡改"
        with pytest.raises(ValidationError):
            context.confirmed_facts[0].value = "1 元"

        fact_item = session.get(FactItem, fixture.fact_item_id)
        style_profile = session.get(
            AccountStyleProfile,
            fixture.style_profile_id,
        )
        source_asset = session.get(FactSource, fixture.source_asset_id)
        assert fact_item is not None
        assert style_profile is not None
        assert source_asset is not None
        fact_item.value = "999 元"
        style_profile.style["title"] = {"hooks": ["数据库已变化"]}
        source_asset.content_sha256 = "b" * 64
        session.flush()

        assert context.confirmed_facts[0].value == "299 元"
        assert '"结论前置"' in context.style.style_json
        assert context.source_assets[0].content_sha256 == "a" * 64


def test_rejects_a_column_style_profile_selected_for_another_column() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        profile = session.get(AccountStyleProfile, fixture.style_profile_id)
        assert profile is not None
        profile.scope_key = f"column:{uuid4()}"
        profile.column_campaign_id = uuid4()
        session.flush()

        with pytest.raises(ValueError, match="style profile.*eligible"):
            _builder(session, fixture).create_run(_inputs(fixture))


def test_rejects_fact_without_manual_confirmation_provenance() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        fact = session.get(FactItem, fixture.fact_item_id)
        assert fact is not None
        fact.confirmed_at = None
        session.flush()

        with pytest.raises(ValueError, match="fact.*eligible"):
            _builder(session, fixture).create_run(_inputs(fixture))


def test_rejects_style_without_manual_confirmation_provenance() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        profile = session.get(AccountStyleProfile, fixture.style_profile_id)
        assert profile is not None
        profile.confirmed_at = None
        session.flush()

        with pytest.raises(ValueError, match="style profile.*eligible"):
            _builder(session, fixture).create_run(_inputs(fixture))


def test_retry_reuses_context_but_changed_inputs_create_a_new_run() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        fixture = _seed(session)
        builder = _builder(session, fixture)
        original = builder.create_run(_inputs(fixture))

        retry = builder.retry(original)
        changed = builder.create_run(
            _inputs(fixture, prompt="改为突出周末旅行")
        )

        assert retry.id != original.id
        assert retry.context is original.context
        assert retry.retry_of_run_id == original.id
        assert changed.id != original.id
        assert changed.retry_of_run_id is None
        assert changed.context is not original.context
        assert changed.context.user_prompt == "改为突出周末旅行"

from datetime import UTC, datetime, timedelta
import os
from threading import Event, Thread
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
    FactSourceKind,
    FactSourceStatus,
)
from app.modules.style_facts.fact_models import FactSourceLevel
from app.modules.style_facts.fact_policy import (
    FactEvidence,
    FactUseDisposition,
    ForcedFactOverride,
    canonicalize_fact_field,
    classify_fact_use,
)
from app.modules.style_facts.source_ingestion import FactSourceService
from app.modules.style_facts.fact_verification import (
    FACT_CONFLICT,
    FactConflictError,
    GeneratedClaim,
    preflight_generation_facts,
    verify_generated_claims,
)
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


NOW = datetime(2026, 7, 23, 4, 0, tzinfo=UTC)


def fact(item_number: int, field_name: str, value: str) -> FactEvidence:
    return FactEvidence(
        item_id=UUID(f"00000000-0000-0000-0000-{item_number:012d}"),
        field_name=field_name,
        value=value,
        level=FactSourceLevel.L2,
        confirmed=True,
        observed_at=NOW,
        max_age=timedelta(days=30),
    )


def test_preflight_returns_stable_fact_conflict_for_unresolved_same_level_values() -> None:
    with pytest.raises(FactConflictError) as raised:
        preflight_generation_facts(
            [fact(1, "价格", "299 元"), fact(2, "价格", "399 元")],
            now=NOW,
        )

    assert raised.value.code == FACT_CONFLICT
    assert raised.value.fields == ("price",)


def test_lower_level_same_level_conflict_still_pauses_when_l1_exists() -> None:
    l1 = FactEvidence(
        item_id=UUID("00000000-0000-0000-0000-000000000001"),
        field_name="价格",
        value="299 元",
        level=FactSourceLevel.L1,
        confirmed=True,
        observed_at=NOW,
        max_age=None,
    )
    lower_first = FactEvidence(
        item_id=UUID("00000000-0000-0000-0000-000000000002"),
        field_name="价格",
        value="199 元",
        level=FactSourceLevel.L3,
        confirmed=True,
        observed_at=NOW,
        max_age=None,
    )
    lower_second = FactEvidence(
        item_id=UUID("00000000-0000-0000-0000-000000000003"),
        field_name="价格",
        value="399 元",
        level=FactSourceLevel.L3,
        confirmed=True,
        observed_at=NOW,
        max_age=None,
    )

    with pytest.raises(FactConflictError) as raised:
        preflight_generation_facts(
            [l1, lower_first, lower_second],
            now=NOW,
        )

    assert raised.value.fields == ("price",)


def test_field_casing_uses_one_canonical_group_for_conflict_detection() -> None:
    with pytest.raises(FactConflictError):
        preflight_generation_facts(
            [fact(1, "Price", "299"), fact(2, "price", "399")],
            now=NOW,
        )


def test_preflight_returns_only_resolved_confirmed_facts() -> None:
    result = preflight_generation_facts(
        [
            fact(1, "价格", "299 元"),
            FactEvidence(
                item_id=UUID("00000000-0000-0000-0000-000000000002"),
                field_name="内部备注",
                value="未确认",
                level=FactSourceLevel.L1,
                confirmed=False,
                observed_at=NOW,
                max_age=None,
            ),
        ],
        now=NOW,
    )

    assert result == {"price": "299 元"}


def test_preflight_accepts_an_audited_override_for_same_level_conflict() -> None:
    first = fact(1, "价格", "299 元")
    selected = fact(2, "价格", "活动价 199 元")
    override = ForcedFactOverride.create(
        selected_item_id=selected.item_id,
        operator_id=UUID("00000000-0000-0000-0000-000000000099"),
        reason="负责人确认活动价已经生效",
        created_at=NOW,
        conflict_item_ids=(first.item_id, selected.item_id),
    )

    result = preflight_generation_facts(
        [first, selected],
        now=NOW,
        overrides={"price": override},
    )

    assert result == {"price": "活动价 199 元"}


def test_confirming_same_level_values_persists_unresolved_conflict_for_preflight() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="冲突持久化工作区")
        session.add(workspace)
        session.flush()
        member = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="事实编辑",
            role=MemberRole.EDITOR,
        )
        session.add(member)
        session.flush()
        sources = [
            FactSource(
                workspace_id=workspace.id,
                kind=FactSourceKind.TEXT,
                level=FactSourceLevel.L2,
                title=f"价格来源 {index}",
                status=FactSourceStatus.PARSED,
                created_by=member.id,
            )
            for index in (1, 2)
        ]
        session.add_all(sources)
        session.flush()
        items = [
            FactItem(
                workspace_id=workspace.id,
                source_id=source.id,
                field_name="价格",
                field_code="price",
                value=value,
                source_location="line 1",
                confidence=1,
                status=FactItemStatus.CANDIDATE,
                conflict_status=FactConflictStatus.CLEAR,
            )
            for source, value in zip(sources, ("299 元", "399 元"), strict=True)
        ]
        session.add_all(items)
        session.flush()
        context = WorkspaceContext(
            workspace_id=workspace.id,
            member_id=member.id,
            role="editor",
        )
        service = FactSourceService(session, context)

        service.confirm_item(items[0].id)
        service.confirm_item(items[1].id)
        session.commit()
        workspace_id = workspace.id

    with Session(engine) as session:
        persisted = list(
            session.scalars(
                select(FactItem)
                .where(FactItem.workspace_id == workspace_id)
                .order_by(FactItem.value)
            )
        )
        assert [item.conflict_status for item in persisted] == [
            FactConflictStatus.UNRESOLVED,
            FactConflictStatus.UNRESOLVED,
        ]
        evidence = [
            FactEvidence(
                item_id=item.id,
                field_name=item.field_name,
                value=item.value,
                level=FactSourceLevel.L2,
                confirmed=item.status is FactItemStatus.CONFIRMED,
                observed_at=NOW,
                max_age=None,
                conflict_status=item.conflict_status,
                persisted_field_code=item.field_code,
            )
            for item in persisted
        ]
        with pytest.raises(FactConflictError) as raised:
            preflight_generation_facts(evidence, now=NOW)
        assert raised.value.code == FACT_CONFLICT


def test_high_risk_claim_conflict_blocks_pending_publication() -> None:
    result = verify_generated_claims(
        [
            GeneratedClaim(field_name="价格", value="399 元"),
            GeneratedClaim(field_name="主色", value="深蓝"),
        ],
        confirmed_facts={"price": "299 元", "color": "深蓝"},
    )

    assert result.can_enter_pending_publication is False
    assert [(issue.field_name, issue.kind) for issue in result.issues] == [
        ("价格", "conflict")
    ]


def test_price_synonym_conflict_is_high_risk_and_blocks_pending_publication() -> None:
    result = verify_generated_claims(
        [GeneratedClaim(field_name="售价", value="399 元")],
        confirmed_facts={"price": "299 元"},
    )

    assert result.can_enter_pending_publication is False
    assert result.issues[0].high_risk is True


@pytest.mark.parametrize(
    "field_name",
    ["标价", "织物", "配料", "规格参数", "作用", "合格证", "安全保证"],
)
def test_unknown_l5_field_names_fail_closed_and_claim_conflicts_block(
    field_name: str,
) -> None:
    field_code = canonicalize_fact_field(field_name).code
    decision = classify_fact_use(field_code, FactSourceLevel.L5)
    result = verify_generated_claims(
        [GeneratedClaim(field_name=field_name, value="另一个值")],
        confirmed_facts={field_code: "已确认值"},
    )

    assert decision.disposition is FactUseDisposition.CANDIDATE_ONLY
    assert result.can_enter_pending_publication is False
    assert result.issues[0].high_risk is True


def test_concurrent_confirmations_serialize_the_workspace_fact_set() -> None:
    database_url = os.getenv(
        "TEST_DATABASE_URL",
        (
            "postgresql+psycopg://operations_ai:local-development-only"
            "@localhost:55432/operations_ai"
        ),
    )
    schema = f"fact_conflict_test_{uuid4().hex}"
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    schema_url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    engine = create_engine(schema_url)
    Base.metadata.create_all(engine)

    try:
        with Session(engine, expire_on_commit=False) as session:
            workspace = Workspace(name="并发事实工作区")
            session.add(workspace)
            session.flush()
            member = WorkspaceMember(
                workspace_id=workspace.id,
                display_name="事实编辑",
                role=MemberRole.EDITOR,
            )
            session.add(member)
            session.flush()
            sources = [
                FactSource(
                    workspace_id=workspace.id,
                    kind=FactSourceKind.TEXT,
                    level=FactSourceLevel.L2,
                    title=f"并发来源 {index}",
                    status=FactSourceStatus.PARSED,
                    created_by=member.id,
                )
                for index in (1, 2)
            ]
            session.add_all(sources)
            session.flush()
            items = [
                FactItem(
                    workspace_id=workspace.id,
                    source_id=source.id,
                    field_name="价格",
                    field_code="price",
                    value=value,
                    source_location="line 1",
                    confidence=1,
                    status=FactItemStatus.CANDIDATE,
                    conflict_status=FactConflictStatus.CLEAR,
                )
                for source, value in zip(
                    sources,
                    ("299 元", "399 元"),
                    strict=True,
                )
            ]
            session.add_all(items)
            session.commit()
            workspace_id = workspace.id
            member_id = member.id
            item_ids = (items[0].id, items[1].id)

        first_reconciled = Event()
        release_first = Event()
        second_reconciled = Event()
        errors: list[BaseException] = []

        def confirm(
            item_id: UUID,
            reconciled: Event,
            release: Event | None = None,
        ) -> None:
            try:
                with Session(engine) as session:
                    service = FactSourceService(
                        session,
                        WorkspaceContext(
                            workspace_id=workspace_id,
                            member_id=member_id,
                            role="editor",
                        ),
                    )
                    service.confirm_item(item_id)
                    reconciled.set()
                    if release is not None:
                        release.wait(timeout=5)
                    session.commit()
            except BaseException as error:
                errors.append(error)
                reconciled.set()

        first = Thread(
            target=confirm,
            args=(item_ids[0], first_reconciled, release_first),
        )
        second = Thread(
            target=confirm,
            args=(item_ids[1], second_reconciled),
        )
        first.start()
        assert first_reconciled.wait(timeout=5)
        second.start()
        try:
            assert not second_reconciled.wait(timeout=0.5)
        finally:
            release_first.set()
            first.join(timeout=5)
            second.join(timeout=5)

        assert errors == []
        assert not first.is_alive()
        assert not second.is_alive()
        with Session(engine) as session:
            statuses = list(
                session.scalars(
                    select(FactItem.conflict_status)
                    .where(FactItem.workspace_id == workspace_id)
                    .order_by(FactItem.value)
                )
            )
        assert statuses == [
            FactConflictStatus.UNRESOLVED,
            FactConflictStatus.UNRESOLVED,
        ]
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_unsupported_high_risk_claim_is_blocked_but_low_risk_claim_is_reported() -> None:
    result = verify_generated_claims(
        [
            GeneratedClaim(field_name="面料", value="羊绒"),
            GeneratedClaim(field_name="主色", value="深蓝"),
        ],
        confirmed_facts={},
    )

    assert result.can_enter_pending_publication is False
    assert [(issue.field_name, issue.kind, issue.high_risk) for issue in result.issues] == [
        ("面料", "unsupported", True),
        ("主色", "unsupported", False),
    ]

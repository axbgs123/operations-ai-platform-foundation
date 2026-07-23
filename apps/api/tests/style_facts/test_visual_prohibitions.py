import pytest
from sqlalchemy import create_engine
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
    FactUseDisposition,
    VisualInferenceField,
    canonicalize_fact_field,
    classify_fact_use,
)
from app.modules.style_facts.source_ingestion import FactSourceService
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [
        ("面料", VisualInferenceField.FABRIC),
        ("面料成分", VisualInferenceField.COMPOSITION),
        ("成分", VisualInferenceField.COMPOSITION),
        ("价格", VisualInferenceField.PRICE),
        ("售价", VisualInferenceField.PRICE),
        ("吊牌价", VisualInferenceField.PRICE),
        ("尺码参数", VisualInferenceField.SIZE_PARAMETERS),
        ("规格尺寸", VisualInferenceField.SIZE_PARAMETERS),
        ("size_parameters", VisualInferenceField.SIZE_PARAMETERS),
        ("功效", VisualInferenceField.EFFICACY),
        ("认证", VisualInferenceField.CERTIFICATION),
        ("产地", VisualInferenceField.ORIGIN),
        ("country_of_origin", VisualInferenceField.ORIGIN),
        ("安全承诺", VisualInferenceField.SAFETY_CLAIM),
        ("安全性", VisualInferenceField.SAFETY_CLAIM),
        ("标价", None),
        ("织物", None),
        ("配料", None),
        ("规格参数", None),
        ("作用", None),
        ("合格证", None),
        ("安全保证", None),
    ],
)
def test_l5_prohibited_visual_fields_are_always_candidate_only(
    field_name: str,
    expected: VisualInferenceField | None,
) -> None:
    decision = classify_fact_use(
        canonicalize_fact_field(field_name).code,
        FactSourceLevel.L5,
    )

    assert decision.visual_field is expected
    assert decision.disposition is FactUseDisposition.CANDIDATE_ONLY


def test_non_visual_or_higher_level_fact_can_be_confirmed() -> None:
    assert (
        classify_fact_use(
            canonicalize_fact_field("主色").code,
            FactSourceLevel.L5,
        ).disposition
        is FactUseDisposition.CONFIRMABLE
    )
    assert canonicalize_fact_field("主色").code == "color"
    assert canonicalize_fact_field("-").code == "custom:unclassified"
    assert canonicalize_fact_field("Straße").code == "custom:straße"
    assert canonicalize_fact_field("ẞ").code == "custom:ß"
    with pytest.raises(ValueError, match="required"):
        canonicalize_fact_field("  ")


def test_l5_prohibited_field_cannot_cross_the_confirmation_boundary() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="视觉禁推工作区")
        session.add(workspace)
        session.flush()
        member = WorkspaceMember(
            workspace_id=workspace.id,
            display_name="事实编辑",
            role=MemberRole.EDITOR,
        )
        session.add(member)
        session.flush()
        source = FactSource(
            workspace_id=workspace.id,
            kind=FactSourceKind.IMAGE,
            level=FactSourceLevel.L5,
            title="视觉推测价格",
            status=FactSourceStatus.PARSED,
            created_by=member.id,
        )
        session.add(source)
        session.flush()
        item = FactItem(
            workspace_id=workspace.id,
            source_id=source.id,
            field_name="售价",
            field_code="price",
            value="399 元",
            source_location="image bbox",
            confidence=0.8,
            status=FactItemStatus.CANDIDATE,
            conflict_status=FactConflictStatus.CLEAR,
        )
        session.add(item)
        session.flush()
        service = FactSourceService(
            session,
            WorkspaceContext(
                workspace_id=workspace.id,
                member_id=member.id,
                role="editor",
            ),
        )

        with pytest.raises(ValueError, match="candidate-only"):
            service.confirm_item(item.id)

        assert item.status is FactItemStatus.CANDIDATE
        item.status = FactItemStatus.CONFIRMED
        legacy_context = service.context()
        assert legacy_context["confirmed_items"] == []
        assert legacy_context["unconstrained_facts"] is True
        assert legacy_context["requires_confirmation"] is True
    assert (
        classify_fact_use(
            canonicalize_fact_field("面料").code,
            FactSourceLevel.L3,
        ).disposition
        is FactUseDisposition.CONFIRMABLE
    )

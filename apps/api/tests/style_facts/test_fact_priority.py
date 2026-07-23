from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
    FactSourceKind,
    FactSourceLevel,
    FactSourceStatus,
)
from app.modules.style_facts.fact_policy import (
    FactEvidence,
    FactResolutionStatus,
    ForcedFactOverride,
    apply_forced_override,
    resolve_fact_field,
)
from app.modules.workspace.models import (
    AuditLog,
    MemberRole,
    Workspace,
    WorkspaceMember,
)


NOW = datetime(2026, 7, 23, 4, 0, tzinfo=UTC)
MEMBER_ID = UUID("00000000-0000-0000-0000-000000000099")


def evidence(
    item_number: int,
    *,
    level: FactSourceLevel,
    value: str,
    age: timedelta = timedelta(days=1),
    max_age: timedelta | None = timedelta(days=30),
) -> FactEvidence:
    return FactEvidence(
        item_id=UUID(f"00000000-0000-0000-0000-{item_number:012d}"),
        field_name="价格",
        value=value,
        level=level,
        confirmed=True,
        observed_at=NOW - age,
        max_age=max_age,
    )


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        (FactSourceLevel.L1, FactSourceLevel.L2),
        (FactSourceLevel.L2, FactSourceLevel.L3),
        (FactSourceLevel.L3, FactSourceLevel.L4),
        (FactSourceLevel.L4, FactSourceLevel.L5),
    ],
)
def test_higher_source_level_wins_without_being_overridden(
    higher: FactSourceLevel,
    lower: FactSourceLevel,
) -> None:
    trusted = evidence(1, level=higher, value="299 元")
    less_trusted = evidence(2, level=lower, value="199 元")

    resolution = resolve_fact_field([less_trusted, trusted], now=NOW)

    assert resolution.status is FactResolutionStatus.RESOLVED
    assert resolution.selected == trusted
    if lower is FactSourceLevel.L5:
        assert resolution.ignored_lower_priority == ()
        assert resolution.candidate_only == (less_trusted,)
    else:
        assert resolution.ignored_lower_priority == (less_trusted,)


def test_expired_higher_level_is_not_selected_over_current_evidence() -> None:
    expired = evidence(
        1,
        level=FactSourceLevel.L1,
        value="旧价格 399 元",
        age=timedelta(days=31),
    )
    current = evidence(2, level=FactSourceLevel.L2, value="现价 299 元")

    resolution = resolve_fact_field([expired, current], now=NOW)

    assert resolution.selected == current
    assert resolution.expired == (expired,)


def test_evidence_expires_exactly_at_the_configured_max_age() -> None:
    at_boundary = evidence(
        1,
        level=FactSourceLevel.L1,
        value="299 元",
        age=timedelta(days=30),
        max_age=timedelta(days=30),
    )

    resolution = resolve_fact_field([at_boundary], now=NOW)

    assert resolution.selected is None
    assert resolution.expired == (at_boundary,)


def test_expiry_rejects_naive_or_future_timestamps() -> None:
    naive = evidence(1, level=FactSourceLevel.L1, value="299 元")
    object.__setattr__(naive, "observed_at", NOW.replace(tzinfo=None))
    with pytest.raises(ValueError, match="timezone"):
        resolve_fact_field([naive], now=NOW)

    future = evidence(2, level=FactSourceLevel.L1, value="299 元")
    object.__setattr__(future, "observed_at", NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match="future"):
        resolve_fact_field([future], now=NOW)


def test_same_level_conflict_is_unresolved_and_pauses_resolution() -> None:
    first = evidence(1, level=FactSourceLevel.L2, value="299 元")
    second = evidence(2, level=FactSourceLevel.L2, value="399 元")

    resolution = resolve_fact_field([first, second], now=NOW)

    assert resolution.status is FactResolutionStatus.UNRESOLVED_CONFLICT
    assert resolution.selected is None
    assert resolution.conflicting == (first, second)


def test_force_override_requires_reason_operator_and_time() -> None:
    with pytest.raises(ValueError, match="reason"):
        ForcedFactOverride.create(
            selected_item_id=evidence(2, level=FactSourceLevel.L3, value="199 元").item_id,
            operator_id=MEMBER_ID,
            reason="  ",
            created_at=NOW,
            conflict_item_ids=(
                evidence(1, level=FactSourceLevel.L1, value="299 元").item_id,
                evidence(2, level=FactSourceLevel.L3, value="199 元").item_id,
            ),
        )


def test_audited_force_override_can_select_lower_level_evidence() -> None:
    higher = evidence(1, level=FactSourceLevel.L1, value="299 元")
    lower = evidence(2, level=FactSourceLevel.L3, value="活动价 199 元")
    override = ForcedFactOverride.create(
        selected_item_id=lower.item_id,
        operator_id=MEMBER_ID,
        reason="负责人确认限时活动价已生效",
        created_at=NOW,
        conflict_item_ids=(higher.item_id, lower.item_id),
    )

    resolution = resolve_fact_field([higher, lower], now=NOW, override=override)

    assert resolution.status is FactResolutionStatus.FORCED_OVERRIDE
    assert resolution.selected == lower
    assert resolution.override == override


def test_force_override_persists_operator_reason_time_and_resolves_conflict() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        workspace = Workspace(name="事实覆盖工作区")
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
                level=level,
                title=f"{level.value} 价格来源",
                status=FactSourceStatus.PARSED,
                created_by=member.id,
            )
            for level in (
                FactSourceLevel.L1,
                FactSourceLevel.L3,
                FactSourceLevel.L4,
            )
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
                status=FactItemStatus.CONFIRMED,
                conflict_status=FactConflictStatus.UNRESOLVED,
                confirmed_by=member.id,
                confirmed_at=NOW,
            )
            for source, value in zip(
                sources,
                ("299 元", "活动价 199 元", "网页价 259 元"),
                strict=True,
            )
        ]
        session.add_all(items)
        session.flush()
        context = WorkspaceContext(
            workspace_id=workspace.id,
            member_id=member.id,
            role="editor",
        )

        override = apply_forced_override(
            session,
            context,
            selected_item_id=items[1].id,
            reason="负责人确认限时活动价已生效",
            clock=lambda: NOW,
        )

        assert override.selected_item_id == items[1].id
        assert set(override.conflict_item_ids) == {item.id for item in items}
        assert all(
            item.conflict_status is FactConflictStatus.RESOLVED for item in items
        )
        assert items[1].override_record == override.as_record()
        assert items[0].override_record is None
        audit = session.scalar(
            select(AuditLog).where(AuditLog.action == "fact_conflict.overridden")
        )
        assert audit is not None
        assert audit.member_id == member.id
        assert audit.details["reason"] == "负责人确认限时活动价已生效"
        assert "299 元" not in str(audit.details)
        assert "199 元" not in str(audit.details)

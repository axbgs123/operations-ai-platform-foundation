from collections.abc import Callable, Iterable
from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import re
import unicodedata
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import utc_now
from app.core.security import WorkspaceContext
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
    FactSourceLevel,
)
from app.modules.workspace.models import AuditLog, Workspace
from app.modules.workspace.permissions import Permission, require_permission


_LEVEL_PRIORITY = {
    FactSourceLevel.L1: 1,
    FactSourceLevel.L2: 2,
    FactSourceLevel.L3: 3,
    FactSourceLevel.L4: 4,
    FactSourceLevel.L5: 5,
}


class FactResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED_CONFLICT = "unresolved_conflict"
    FORCED_OVERRIDE = "forced_override"
    NO_CONFIRMED_FACT = "no_confirmed_fact"


class FactUseDisposition(StrEnum):
    CONFIRMABLE = "confirmable"
    CANDIDATE_ONLY = "candidate_only"


class VisualInferenceField(StrEnum):
    FABRIC = "fabric"
    COMPOSITION = "composition"
    PRICE = "price"
    SIZE_PARAMETERS = "size_parameters"
    EFFICACY = "efficacy"
    CERTIFICATION = "certification"
    ORIGIN = "origin"
    SAFETY_CLAIM = "safety_claim"


class SafeVisualField(StrEnum):
    COLOR = "color"


_FIELD_TOKEN_RULES: tuple[tuple[VisualInferenceField, tuple[str, ...]], ...] = (
    (
        VisualInferenceField.COMPOSITION,
        ("面料成分", "成分", "composition", "ingredient", "fibercontent"),
    ),
    (
        VisualInferenceField.PRICE,
        ("价格", "售价", "吊牌价", "零售价", "price", "msrp", "rrp", "cost"),
    ),
    (
        VisualInferenceField.SIZE_PARAMETERS,
        (
            "尺码参数",
            "尺码",
            "规格尺寸",
            "尺寸",
            "sizeparameters",
            "sizeparameter",
            "size",
            "dimension",
            "measurement",
        ),
    ),
    (
        VisualInferenceField.EFFICACY,
        ("功效", "效果", "efficacy", "benefit", "effect"),
    ),
    (
        VisualInferenceField.CERTIFICATION,
        ("认证", "资质", "certification", "certificate", "certified"),
    ),
    (
        VisualInferenceField.ORIGIN,
        ("原产地", "产地", "countryoforigin", "madein", "origin"),
    ),
    (
        VisualInferenceField.SAFETY_CLAIM,
        ("安全承诺", "安全性", "无毒", "safetyclaim", "safety", "nontoxic"),
    ),
    (
        VisualInferenceField.FABRIC,
        ("面料", "材质", "fabric", "material"),
    ),
)

_SAFE_VISUAL_FIELD_ALIASES: dict[str, SafeVisualField] = {
    "主色": SafeVisualField.COLOR,
    "颜色": SafeVisualField.COLOR,
    "color": SafeVisualField.COLOR,
    "primarycolor": SafeVisualField.COLOR,
}


def _normalized_field(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\W_]+", "", normalized)


def canonicalize_fact_value(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


@dataclass(frozen=True)
class CanonicalFactField:
    code: str
    visual_field: VisualInferenceField | None


def canonicalize_fact_field(field_name: str) -> CanonicalFactField:
    if not field_name.strip():
        raise ValueError("fact field name is required")
    normalized = _normalized_field(field_name)
    if not normalized:
        return CanonicalFactField(
            code="custom:unclassified",
            visual_field=None,
        )
    safe_visual_field = _SAFE_VISUAL_FIELD_ALIASES.get(normalized)
    if safe_visual_field is not None:
        return CanonicalFactField(code=safe_visual_field.value, visual_field=None)
    for visual_field, tokens in _FIELD_TOKEN_RULES:
        if normalized == visual_field.value.replace("_", "") or normalized in tokens:
            return CanonicalFactField(
                code=visual_field.value,
                visual_field=visual_field,
            )
    return CanonicalFactField(code=f"custom:{normalized}", visual_field=None)


def _visual_field_for_code(field_code: str) -> VisualInferenceField | None:
    try:
        return VisualInferenceField(field_code)
    except ValueError:
        try:
            SafeVisualField(field_code)
            return None
        except ValueError:
            pass
        if not field_code.startswith("custom:") or not field_code.removeprefix(
            "custom:"
        ):
            raise ValueError("unknown canonical fact field code") from None
        return None


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} timezone is required")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class FactEvidence:
    item_id: UUID
    field_name: str
    value: str
    level: FactSourceLevel
    confirmed: bool
    observed_at: datetime
    max_age: timedelta | None
    conflict_status: FactConflictStatus = FactConflictStatus.CLEAR
    persisted_field_code: InitVar[str | None] = None
    field_code: str = field(init=False)

    def __post_init__(self, persisted_field_code: str | None) -> None:
        canonical = canonicalize_fact_field(self.field_name).code
        if persisted_field_code is not None and persisted_field_code != canonical:
            raise ValueError("persisted fact field code does not match its display name")
        if self.max_age is not None and self.max_age < timedelta(0):
            raise ValueError("fact evidence max age cannot be negative")
        object.__setattr__(self, "field_code", canonical)
        object.__setattr__(
            self,
            "observed_at",
            _require_aware(self.observed_at, "fact evidence observed_at"),
        )

    def is_expired(self, now: datetime) -> bool:
        checked_now = _require_aware(now, "fact policy now")
        observed_at = _require_aware(
            self.observed_at,
            "fact evidence observed_at",
        )
        if observed_at > checked_now:
            raise ValueError("fact evidence observed_at cannot be in the future")
        if self.max_age is None:
            return False
        return checked_now - observed_at >= self.max_age


@dataclass(frozen=True)
class ForcedFactOverride:
    selected_item_id: UUID
    operator_id: UUID
    reason: str
    created_at: datetime
    conflict_item_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        normalized_reason = self.reason.strip()
        if not normalized_reason:
            raise ValueError("force override reason is required")
        if not isinstance(self.operator_id, UUID):
            raise ValueError("force override operator is required")
        unique_ids = tuple(sorted(set(self.conflict_item_ids), key=str))
        if len(unique_ids) < 2:
            raise ValueError("force override requires a complete conflict group")
        if self.selected_item_id not in unique_ids:
            raise ValueError("selected fact must be part of the conflict")
        object.__setattr__(self, "reason", normalized_reason)
        object.__setattr__(
            self,
            "created_at",
            _require_aware(self.created_at, "force override created_at"),
        )
        object.__setattr__(self, "conflict_item_ids", unique_ids)

    @classmethod
    def create(
        cls,
        *,
        selected_item_id: UUID,
        operator_id: UUID,
        reason: str,
        created_at: datetime,
        conflict_item_ids: Iterable[UUID],
    ) -> "ForcedFactOverride":
        return cls(
            selected_item_id=selected_item_id,
            operator_id=operator_id,
            reason=reason,
            created_at=created_at,
            conflict_item_ids=tuple(conflict_item_ids),
        )

    def as_record(self) -> dict[str, object]:
        return {
            "selected_item_id": str(self.selected_item_id),
            "operator_id": str(self.operator_id),
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "conflict_item_ids": [str(item_id) for item_id in self.conflict_item_ids],
        }


@dataclass(frozen=True)
class FactUseDecision:
    disposition: FactUseDisposition
    visual_field: VisualInferenceField | None


@dataclass(frozen=True)
class FactResolution:
    status: FactResolutionStatus
    selected: FactEvidence | None
    conflicting: tuple[FactEvidence, ...] = ()
    ignored_lower_priority: tuple[FactEvidence, ...] = ()
    candidate_only: tuple[FactEvidence, ...] = ()
    expired: tuple[FactEvidence, ...] = ()
    override: ForcedFactOverride | None = None


def classify_fact_use(
    field_code: str,
    level: FactSourceLevel,
) -> FactUseDecision:
    visual_field = _visual_field_for_code(field_code)
    disposition = (
        FactUseDisposition.CANDIDATE_ONLY
        if level is FactSourceLevel.L5
        and field_code not in {safe_field.value for safe_field in SafeVisualField}
        else FactUseDisposition.CONFIRMABLE
    )
    return FactUseDecision(disposition=disposition, visual_field=visual_field)


def is_high_risk_fact_field_code(field_code: str) -> bool:
    visual_field = _visual_field_for_code(field_code)
    return visual_field is not None or field_code.startswith("custom:")


def resolve_fact_field(
    evidence: list[FactEvidence],
    *,
    now: datetime,
    override: ForcedFactOverride | None = None,
) -> FactResolution:
    field_codes = {item.field_code for item in evidence}
    if len(field_codes) > 1:
        raise ValueError("fact resolution accepts one canonical field at a time")
    expired = tuple(item for item in evidence if item.is_expired(now))
    candidate_only = tuple(
        item
        for item in evidence
        if item.confirmed
        and item not in expired
        and classify_fact_use(item.field_code, item.level).disposition
        is FactUseDisposition.CANDIDATE_ONLY
    )
    usable = [
        item
        for item in evidence
        if item.confirmed and item not in expired and item not in candidate_only
    ]
    if override is not None:
        if set(override.conflict_item_ids) != {item.item_id for item in usable}:
            raise ValueError("force override does not cover the complete current fact set")
        selected = next(
            (item for item in usable if item.item_id == override.selected_item_id),
            None,
        )
        if selected is None:
            raise ValueError("force override must select current confirmed evidence")
        return FactResolution(
            status=FactResolutionStatus.FORCED_OVERRIDE,
            selected=selected,
            candidate_only=candidate_only,
            expired=expired,
            override=override,
        )
    if not usable:
        return FactResolution(
            status=FactResolutionStatus.NO_CONFIRMED_FACT,
            selected=None,
            candidate_only=candidate_only,
            expired=expired,
        )
    conflicts: list[FactEvidence] = [
        item
        for item in usable
        if item.conflict_status is FactConflictStatus.UNRESOLVED
    ]
    for level in FactSourceLevel:
        at_level = [item for item in usable if item.level is level]
        if len({canonicalize_fact_value(item.value) for item in at_level}) > 1:
            conflicts.extend(at_level)
    if conflicts:
        conflict_ids = {item.item_id for item in conflicts}
        return FactResolution(
            status=FactResolutionStatus.UNRESOLVED_CONFLICT,
            selected=None,
            conflicting=tuple(
                item for item in usable if item.item_id in conflict_ids
            ),
            candidate_only=candidate_only,
            expired=expired,
        )
    highest_priority = min(_LEVEL_PRIORITY[item.level] for item in usable)
    highest = tuple(
        item for item in usable if _LEVEL_PRIORITY[item.level] == highest_priority
    )
    selected = highest[0]
    return FactResolution(
        status=FactResolutionStatus.RESOLVED,
        selected=selected,
        ignored_lower_priority=tuple(item for item in usable if item not in highest),
        candidate_only=candidate_only,
        expired=expired,
    )


def _lock_workspace_fact_policy(
    session: Session,
    workspace_id: UUID,
) -> None:
    locked_workspace_id = session.scalar(
        select(Workspace.id)
        .where(Workspace.id == workspace_id)
        .with_for_update()
    )
    if locked_workspace_id is None:
        raise LookupError("workspace not found")


def reconcile_fact_conflicts(
    session: Session,
    context: WorkspaceContext,
    *,
    field_code: str,
) -> list[FactItem]:
    require_permission(context.role, Permission.MANAGE_FACTS)
    _lock_workspace_fact_policy(session, context.workspace_id)
    rows = session.execute(
        select(FactItem, FactSource.level)
        .join(FactSource, FactSource.id == FactItem.source_id)
        .where(
            FactItem.workspace_id == context.workspace_id,
            FactItem.field_code == field_code,
            FactItem.status == FactItemStatus.CONFIRMED,
        )
        .with_for_update()
    ).all()
    items = [row[0] for row in rows]
    for item in items:
        item.conflict_status = FactConflictStatus.CLEAR
        item.override_record = None
    for level in FactSourceLevel:
        at_level = [row[0] for row in rows if row[1] is level]
        if len({canonicalize_fact_value(item.value) for item in at_level}) > 1:
            for item in at_level:
                item.conflict_status = FactConflictStatus.UNRESOLVED
    session.flush()
    return items


def apply_forced_override(
    session: Session,
    context: WorkspaceContext,
    *,
    selected_item_id: UUID,
    reason: str,
    clock: Callable[[], datetime] = utc_now,
) -> ForcedFactOverride:
    require_permission(context.role, Permission.MANAGE_FACTS)
    if context.member_id is None:
        raise ValueError("force override requires an authenticated member")
    _lock_workspace_fact_policy(session, context.workspace_id)
    selected = session.scalar(
        select(FactItem).where(
            FactItem.workspace_id == context.workspace_id,
            FactItem.id == selected_item_id,
        )
    )
    if selected is None:
        raise LookupError("selected fact item not found")
    if selected.status is not FactItemStatus.CONFIRMED:
        raise ValueError("force override must select a confirmed fact")
    rows = session.execute(
        select(FactItem, FactSource.level)
        .join(FactSource, FactSource.id == FactItem.source_id)
        .where(
            FactItem.workspace_id == context.workspace_id,
            FactItem.field_code == selected.field_code,
            FactItem.status == FactItemStatus.CONFIRMED,
        )
        .with_for_update()
    ).all()
    items = [
        row[0]
        for row in rows
        if classify_fact_use(row[0].field_code, row[1]).disposition
        is FactUseDisposition.CONFIRMABLE
    ]
    if selected not in items:
        raise ValueError("candidate-only visual fact cannot be force overridden")
    if len(items) < 2 or len(
        {canonicalize_fact_value(item.value) for item in items}
    ) < 2:
        raise ValueError("force override requires a real conflicting fact set")
    override = ForcedFactOverride.create(
        selected_item_id=selected_item_id,
        operator_id=context.member_id,
        reason=reason,
        created_at=clock(),
        conflict_item_ids=(item.id for item in items),
    )
    for item in items:
        item.conflict_status = FactConflictStatus.RESOLVED
        item.override_record = None
    selected.override_record = override.as_record()
    session.add(
        AuditLog(
            workspace_id=context.workspace_id,
            action="fact_conflict.overridden",
            resource_type="fact_item",
            resource_id=selected.id,
            member_id=context.member_id,
            details={
                "field_code": selected.field_code,
                "selected_item_id": str(selected.id),
                "conflict_item_ids": [
                    str(item_id) for item_id in override.conflict_item_ids
                ],
                "reason": override.reason,
                "created_at": override.created_at.isoformat(),
            },
        )
    )
    session.flush()
    return override

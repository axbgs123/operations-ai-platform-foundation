import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import (
    BenchmarkProfile,
    ColumnCampaign,
    ColumnCampaignKind,
    ObjectiveProfile,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import Content, ContentStatus
from app.modules.exports.manifest import (
    BackupManifest,
    PortableRecord,
    RecordType,
    canonical_manifest_json,
)
from app.modules.metrics.models import (
    ContentType,
    DataSnapshot,
    MetricAggregation,
    MetricDefinition,
    MetricUnit,
    SnapshotMetricValue,
    SnapshotSource,
)
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentArtifactKind,
    AgentBriefing,
    AgentEvent,
    AgentPlan,
    AgentPlanStatus,
    AgentRun,
    AgentRunStatus,
    AgentRunStep,
    AgentStepStatus,
    AgentToolRisk,
)
from app.modules.operations_agent.schemas import (
    AgentPlanApprovalSnapshot,
    AgentPlanDocument,
    AgentPlanStep,
    StoredAgentPlanDocument,
)
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)
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
    StyleSample,
)
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


class RestoreMode(StrEnum):
    NEW = "new"
    MERGE = "merge"


class RestoreAction(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"
    SKIP = "skip"
    CONFLICT = "conflict"


class RestorePreviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    record_type: RecordType
    source_id: UUID
    target_id: UUID | None
    action: RestoreAction
    reason: str
    blocking: bool
    conflict_summary: str | None = None


class RestorePreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_id: str
    manifest_fingerprint: str
    mode: RestoreMode
    target_workspace_id: UUID | None
    items: tuple[RestorePreviewItem, ...]
    blocked: bool


MODEL_BY_TYPE = {
    RecordType.PLATFORM_ACCOUNT: PlatformAccount,
    RecordType.OBJECTIVE_PROFILE: ObjectiveProfile,
    RecordType.BENCHMARK_PROFILE: BenchmarkProfile,
    RecordType.COLUMN_CAMPAIGN: ColumnCampaign,
    RecordType.METRIC_DEFINITION: MetricDefinition,
    RecordType.CONTENT: Content,
    RecordType.DATA_SNAPSHOT: DataSnapshot,
    RecordType.SNAPSHOT_METRIC_VALUE: SnapshotMetricValue,
    RecordType.STYLE_PROFILE: AccountStyleProfile,
    RecordType.STYLE_SAMPLE: StyleSample,
    RecordType.FACT_SOURCE_METADATA: FactSource,
    RecordType.FACT_ITEM: FactItem,
    RecordType.RISK_DOCUMENT_METADATA: RiskDocument,
    RecordType.AGENT_BRIEFING: AgentBriefing,
    RecordType.AGENT_PLAN: AgentPlan,
    RecordType.AGENT_RUN: AgentRun,
    RecordType.AGENT_STEP: AgentRunStep,
    RecordType.AGENT_ARTIFACT: AgentArtifact,
    RecordType.AGENT_EVENT: AgentEvent,
}
OVERWRITABLE_TYPES = {
    RecordType.PLATFORM_ACCOUNT,
    RecordType.OBJECTIVE_PROFILE,
    RecordType.BENCHMARK_PROFILE,
    RecordType.COLUMN_CAMPAIGN,
    RecordType.METRIC_DEFINITION,
    RecordType.CONTENT,
}
APPLY_ORDER = {
    RecordType.PLATFORM_ACCOUNT: 0,
    RecordType.OBJECTIVE_PROFILE: 1,
    RecordType.BENCHMARK_PROFILE: 2,
    RecordType.METRIC_DEFINITION: 3,
    RecordType.COLUMN_CAMPAIGN: 4,
    RecordType.CONTENT: 5,
    RecordType.ASSET_REFERENCE: 6,
    RecordType.DATA_SNAPSHOT: 7,
    RecordType.SNAPSHOT_METRIC_VALUE: 8,
    RecordType.STYLE_PROFILE: 6,
    RecordType.STYLE_SAMPLE: 7,
    RecordType.FACT_SOURCE_METADATA: 0,
    RecordType.FACT_ITEM: 8,
    RecordType.RISK_DOCUMENT_METADATA: 1,
    RecordType.AGENT_BRIEFING: 9,
    RecordType.AGENT_PLAN: 10,
    RecordType.AGENT_RUN: 11,
    RecordType.AGENT_STEP: 12,
    RecordType.AGENT_ARTIFACT: 13,
    RecordType.AGENT_EVENT: 14,
}
AGENT_HISTORY_TYPES = {
    RecordType.AGENT_BRIEFING,
    RecordType.AGENT_PLAN,
    RecordType.AGENT_RUN,
    RecordType.AGENT_STEP,
    RecordType.AGENT_ARTIFACT,
    RecordType.AGENT_EVENT,
}


def _target_workspace_id(
    context: WorkspaceContext,
    manifest: BackupManifest,
    mode: RestoreMode,
    idempotency_key: str,
) -> UUID:
    if mode is RestoreMode.MERGE:
        return context.workspace_id
    return uuid5(
        context.workspace_id,
        "lightweight-restore:"
        f"{manifest.workspace.source_id}:{idempotency_key.strip()}",
    )


def _target_id(
    target_workspace_id: UUID,
    manifest: BackupManifest,
    record: PortableRecord,
) -> UUID:
    if target_workspace_id == manifest.workspace.source_id:
        return record.source_id
    return uuid5(
        target_workspace_id,
        f"{record.record_type.value}:{record.source_id}",
    )


def _required_platform(record: PortableRecord) -> Platform:
    if record.platform is None:
        raise ValueError("platform-scoped restore record is missing platform")
    return Platform(record.platform)


def _portable(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _portable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item) for item in value]
    return value


def _current_data(record_type: RecordType, instance: Any) -> dict[str, Any]:
    if record_type is RecordType.PLATFORM_ACCOUNT:
        return {"name": instance.name}
    if record_type is RecordType.OBJECTIVE_PROFILE:
        return {
            "account_id": str(instance.account_id),
            "version": instance.version,
            "objectives": instance.objectives,
            "metric_weights": instance.metric_weights,
            "is_account_default": instance.is_account_default,
        }
    if record_type is RecordType.BENCHMARK_PROFILE:
        return {
            "account_id": str(instance.account_id),
            "version": instance.version,
            "sample_size": instance.sample_size,
            "is_account_default": instance.is_account_default,
        }
    if record_type is RecordType.COLUMN_CAMPAIGN:
        return {
            "account_id": str(instance.account_id),
            "name": instance.name,
            "kind": instance.kind.value,
            "starts_at": _portable(instance.starts_at),
            "ends_at": _portable(instance.ends_at),
            "objective_profile_id": _portable(instance.objective_profile_id),
            "benchmark_profile_id": _portable(instance.benchmark_profile_id),
        }
    if record_type is RecordType.METRIC_DEFINITION:
        return {
            "content_type": instance.content_type.value,
            "key": instance.key,
            "label": instance.label,
            "unit": instance.unit.value,
            "aggregation": instance.aggregation.value,
            "higher_is_better": instance.higher_is_better,
            "is_default": instance.is_default,
        }
    if record_type is RecordType.CONTENT:
        return {
            "account_id": str(instance.account_id),
            "objective_profile_id": str(instance.objective_profile_id),
            "benchmark_profile_id": str(instance.benchmark_profile_id),
            "content_type": instance.content_type.value,
            "column_campaign_id": _portable(instance.column_campaign_id),
            "title": instance.title,
            "body": instance.body,
            "work_url": instance.work_url,
            "platform_content_id": instance.platform_content_id,
            "status": instance.status.value,
            "published_title": instance.published_title,
            "published_body": instance.published_body,
            "published_at": _portable(instance.published_at),
            "deleted_at": _portable(instance.deleted_at),
        }
    if record_type is RecordType.DATA_SNAPSHOT:
        return {
            "content_id": str(instance.content_id),
            "account_id": str(instance.account_id),
            "content_type": instance.content_type.value,
            "collected_at": instance.collected_at.isoformat(),
            "age_seconds": instance.age_seconds,
            "maturity_bucket": instance.maturity_bucket,
            "source": instance.source.value,
            "confirmed": instance.confirmed,
            "confirmed_at": _portable(instance.confirmed_at),
            "original_screenshot_asset_id": None,
        }
    if record_type is RecordType.SNAPSHOT_METRIC_VALUE:
        return {
            "snapshot_id": str(instance.snapshot_id),
            "metric_key": instance.metric_key,
            "raw_value": _portable(instance.raw_value),
            "normalized_value": _portable(instance.normalized_value),
            "ocr_confidence": instance.ocr_confidence,
            "eligible_for_benchmark": instance.eligible_for_benchmark,
            "metric_definition_id": _portable(instance.metric_definition_id),
        }
    if record_type is RecordType.STYLE_PROFILE:
        return {
            "account_id": str(instance.account_id),
            "scope_key": instance.scope_key,
            "version": instance.version,
            "status": instance.status.value,
            "style": instance.style,
            "sample_content_ids": instance.sample_content_ids,
            "diff": instance.diff,
            "column_campaign_id": _portable(instance.column_campaign_id),
            "base_profile_id": _portable(instance.base_profile_id),
            "confirmed_at": _portable(instance.confirmed_at),
        }
    if record_type is RecordType.STYLE_SAMPLE:
        return {
            "account_id": str(instance.account_id),
            "scope_key": instance.scope_key,
            "content_id": str(instance.content_id),
            "column_campaign_id": _portable(instance.column_campaign_id),
            "selected_at": instance.selected_at.isoformat(),
        }
    if record_type is RecordType.FACT_SOURCE_METADATA:
        return {
            "kind": instance.kind.value,
            "level": instance.level.value,
            "title": instance.title,
            "status": instance.status.value,
            "source_url": instance.source_url,
            "file_name": instance.file_name,
            "mime_type": instance.mime_type,
            "size": instance.size,
            "published_at": _portable(instance.published_at),
            "accessed_at": _portable(instance.accessed_at),
            "untrusted_data": instance.untrusted_data,
        }
    if record_type is RecordType.FACT_ITEM:
        return {
            "source_id": str(instance.source_id),
            "field_name": instance.field_name,
            "field_code": instance.field_code,
            "value": instance.value,
            "source_location": instance.source_location,
            "confidence": instance.confidence,
            "status": instance.status.value,
            "conflict_status": instance.conflict_status.value,
            "confirmed_at": _portable(instance.confirmed_at),
        }
    if record_type is RecordType.RISK_DOCUMENT_METADATA:
        return {
            "scope": instance.scope.value,
            "source_level": instance.source_level.value,
            "title": instance.title,
            "authorization_status": instance.authorization_status.value,
            "status": instance.status.value,
            "version": instance.version,
            "source_url": instance.source_url,
            "private_document_id": instance.private_document_id,
            "published_at": _portable(instance.published_at),
            "effective_at": _portable(instance.effective_at),
            "accessed_at": _portable(instance.accessed_at),
            "previous_version_id": _portable(instance.previous_version_id),
            "file_name": instance.file_name,
            "mime_type": instance.mime_type,
            "untrusted_data": instance.untrusted_data,
            "redistribution_authorized": instance.redistribution_authorized,
        }
    raise ValueError("unsupported restore record")


def _mapped_data(
    record: PortableRecord,
    manifest: BackupManifest,
    target_workspace_id: UUID,
) -> dict[str, Any]:
    by_identity = {
        (item.record_type, item.source_id): item for item in manifest.records
    }
    mapped = dict(record.data)
    reference_types = {
        RecordType.OBJECTIVE_PROFILE: {
            "account_id": RecordType.PLATFORM_ACCOUNT,
        },
        RecordType.BENCHMARK_PROFILE: {
            "account_id": RecordType.PLATFORM_ACCOUNT,
        },
        RecordType.COLUMN_CAMPAIGN: {
            "account_id": RecordType.PLATFORM_ACCOUNT,
            "objective_profile_id": RecordType.OBJECTIVE_PROFILE,
            "benchmark_profile_id": RecordType.BENCHMARK_PROFILE,
        },
        RecordType.CONTENT: {
            "account_id": RecordType.PLATFORM_ACCOUNT,
            "objective_profile_id": RecordType.OBJECTIVE_PROFILE,
            "benchmark_profile_id": RecordType.BENCHMARK_PROFILE,
            "column_campaign_id": RecordType.COLUMN_CAMPAIGN,
        },
        RecordType.ASSET_REFERENCE: {
            "content_id": RecordType.CONTENT,
        },
        RecordType.DATA_SNAPSHOT: {
            "content_id": RecordType.CONTENT,
            "account_id": RecordType.PLATFORM_ACCOUNT,
            "original_screenshot_asset_id": RecordType.ASSET_REFERENCE,
        },
        RecordType.SNAPSHOT_METRIC_VALUE: {
            "snapshot_id": RecordType.DATA_SNAPSHOT,
            "metric_definition_id": RecordType.METRIC_DEFINITION,
        },
        RecordType.STYLE_PROFILE: {
            "account_id": RecordType.PLATFORM_ACCOUNT,
            "column_campaign_id": RecordType.COLUMN_CAMPAIGN,
            "base_profile_id": RecordType.STYLE_PROFILE,
        },
        RecordType.STYLE_SAMPLE: {
            "account_id": RecordType.PLATFORM_ACCOUNT,
            "content_id": RecordType.CONTENT,
            "column_campaign_id": RecordType.COLUMN_CAMPAIGN,
        },
        RecordType.FACT_ITEM: {
            "source_id": RecordType.FACT_SOURCE_METADATA,
        },
        RecordType.RISK_DOCUMENT_METADATA: {
            "previous_version_id": RecordType.RISK_DOCUMENT_METADATA,
        },
        RecordType.AGENT_PLAN: {
            "briefing_id": RecordType.AGENT_BRIEFING,
            "account_id": RecordType.PLATFORM_ACCOUNT,
        },
        RecordType.AGENT_RUN: {
            "plan_id": RecordType.AGENT_PLAN,
            "account_id": RecordType.PLATFORM_ACCOUNT,
        },
        RecordType.AGENT_STEP: {
            "run_id": RecordType.AGENT_RUN,
        },
        RecordType.AGENT_ARTIFACT: {
            "run_id": RecordType.AGENT_RUN,
            "step_id": RecordType.AGENT_STEP,
        },
        RecordType.AGENT_EVENT: {
            "run_id": RecordType.AGENT_RUN,
            "step_id": RecordType.AGENT_STEP,
        },
    }
    for field, target_type in reference_types.get(record.record_type, {}).items():
        raw = mapped.get(field)
        if raw is None:
            continue
        source_id = UUID(str(raw))
        target_record = by_identity[(target_type, source_id)]
        mapped[field] = str(
            _target_id(target_workspace_id, manifest, target_record)
        )
    if record.record_type is RecordType.DATA_SNAPSHOT:
        mapped["original_screenshot_asset_id"] = None
    if record.record_type is RecordType.STYLE_PROFILE:
        mapped["sample_content_ids"] = [
            str(
                _target_id(
                    target_workspace_id,
                    manifest,
                    by_identity[(RecordType.CONTENT, UUID(str(source_id)))],
                )
            )
            for source_id in record.data["sample_content_ids"]
        ]
    return mapped


def _platform_mismatch(
    record: PortableRecord,
    records: dict[tuple[RecordType, UUID], PortableRecord],
) -> bool:
    def referenced(record_type: RecordType, field: str) -> PortableRecord | None:
        raw = record.data.get(field)
        if raw is None:
            return None
        return records.get((record_type, UUID(str(raw))))

    if record.record_type in {
        RecordType.OBJECTIVE_PROFILE,
        RecordType.BENCHMARK_PROFILE,
        RecordType.COLUMN_CAMPAIGN,
        RecordType.FACT_SOURCE_METADATA,
        RecordType.FACT_ITEM,
        RecordType.RISK_DOCUMENT_METADATA,
        RecordType.AGENT_BRIEFING,
        RecordType.AGENT_STEP,
        RecordType.AGENT_ARTIFACT,
        RecordType.AGENT_EVENT,
    }:
        return False
    if record.record_type is RecordType.AGENT_PLAN:
        account = referenced(RecordType.PLATFORM_ACCOUNT, "account_id")
        return account is None or record.platform != account.platform
    if record.record_type is RecordType.AGENT_RUN:
        account = referenced(RecordType.PLATFORM_ACCOUNT, "account_id")
        plan = referenced(RecordType.AGENT_PLAN, "plan_id")
        return (
            account is None
            or plan is None
            or record.platform != account.platform
            or record.platform != plan.platform
        )
    if record.record_type in {
        RecordType.STYLE_PROFILE,
        RecordType.STYLE_SAMPLE,
    }:
        account = referenced(RecordType.PLATFORM_ACCOUNT, "account_id")
        content = (
            referenced(RecordType.CONTENT, "content_id")
            if record.record_type is RecordType.STYLE_SAMPLE
            else None
        )
        sample_contents = (
            [
                records.get((RecordType.CONTENT, UUID(str(source_id))))
                for source_id in record.data["sample_content_ids"]
            ]
            if record.record_type is RecordType.STYLE_PROFILE
            else []
        )
        return (
            account is None
            or record.platform != account.platform
            or (content is not None and record.platform != content.platform)
            or any(
                sample is None or record.platform != sample.platform
                for sample in sample_contents
            )
        )
    if record.record_type is RecordType.CONTENT:
        account = referenced(RecordType.PLATFORM_ACCOUNT, "account_id")
        return account is None or record.platform != account.platform
    if record.record_type is RecordType.DATA_SNAPSHOT:
        account = referenced(RecordType.PLATFORM_ACCOUNT, "account_id")
        content = referenced(RecordType.CONTENT, "content_id")
        return (
            account is None
            or content is None
            or record.platform != account.platform
            or record.platform != content.platform
            or record.data["content_type"] != content.data["content_type"]
        )
    if record.record_type is RecordType.SNAPSHOT_METRIC_VALUE:
        snapshot = referenced(RecordType.DATA_SNAPSHOT, "snapshot_id")
        definition = referenced(
            RecordType.METRIC_DEFINITION, "metric_definition_id"
        )
        return (
            snapshot is None
            or (
                definition is not None
                and (
                    snapshot.platform != definition.platform
                    or snapshot.data["content_type"]
                    != definition.data["content_type"]
                )
            )
        )
    return False


def build_restore_preview(
    session: Session,
    context: WorkspaceContext,
    manifest: BackupManifest,
    *,
    mode: RestoreMode,
    idempotency_key: str,
) -> RestorePreview:
    if context.role != "admin":
        raise PermissionError("admin role required")
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise ValueError("valid idempotency key is required")
    if mode is RestoreMode.MERGE:
        workspace = session.scalar(
            select(Workspace.id).where(Workspace.id == context.workspace_id)
        )
        if workspace is None:
            raise LookupError("target workspace not found")
    target_workspace_id = _target_workspace_id(
        context,
        manifest,
        mode,
        idempotency_key,
    )
    target_workspace_exists = session.get(Workspace, target_workspace_id) is not None
    records = {
        (record.record_type, record.source_id): record
        for record in manifest.records
    }
    items: list[RestorePreviewItem] = []
    for record in sorted(
        manifest.records,
        key=lambda item: (item.record_type.value, str(item.source_id)),
    ):
        target_id = _target_id(target_workspace_id, manifest, record)
        if record.record_type is RecordType.ASSET_REFERENCE:
            items.append(
                RestorePreviewItem(
                    record_type=record.record_type,
                    source_id=record.source_id,
                    target_id=None,
                    action=RestoreAction.SKIP,
                    reason="media_body_omitted_from_lightweight_backup",
                    blocking=False,
                )
            )
            continue
        if _platform_mismatch(record, records):
            items.append(
                RestorePreviewItem(
                    record_type=record.record_type,
                    source_id=record.source_id,
                    target_id=target_id,
                    action=RestoreAction.CONFLICT,
                    reason="platform_reference_mismatch",
                    blocking=True,
                    conflict_summary="平台或引用范围不兼容",
                )
            )
            continue
        if mode is RestoreMode.NEW and not target_workspace_exists:
            items.append(
                RestorePreviewItem(
                    record_type=record.record_type,
                    source_id=record.source_id,
                    target_id=target_id,
                    action=RestoreAction.CREATE,
                    reason="new_workspace_record",
                    blocking=False,
                )
            )
            continue
        model = MODEL_BY_TYPE[record.record_type]
        existing = session.get(cast(Any, model), target_id)
        if existing is None:
            action = RestoreAction.CREATE
            reason = "record_not_present"
            blocking = False
            summary = None
        elif existing.workspace_id != target_workspace_id:
            action = RestoreAction.CONFLICT
            reason = "workspace_scope_mismatch"
            blocking = True
            summary = "目标标识属于其他工作区"
        elif record.record_type in AGENT_HISTORY_TYPES:
            action = RestoreAction.SKIP
            reason = "read_only_history_already_imported"
            blocking = False
            summary = None
        else:
            expected = _portable(
                _mapped_data(record, manifest, target_workspace_id)
            )
            current = _portable(_current_data(record.record_type, existing))
            existing_platform = getattr(existing, "platform", None)
            platform_matches = (
                record.platform is None
                or existing_platform is None
                or record.platform == _portable(existing_platform)
            )
            if not platform_matches:
                action = RestoreAction.CONFLICT
                reason = "platform_mismatch"
                blocking = True
                summary = "目标记录的平台不兼容"
            elif current == expected:
                action = RestoreAction.SKIP
                reason = "identical_record"
                blocking = False
                summary = None
            elif record.record_type in OVERWRITABLE_TYPES:
                action = RestoreAction.OVERWRITE
                reason = "safe_mutable_fields_changed"
                blocking = False
                summary = "可迁移字段存在差异"
            else:
                action = RestoreAction.CONFLICT
                reason = "immutable_record_changed"
                blocking = True
                summary = "不可变历史记录存在差异"
        items.append(
            RestorePreviewItem(
                record_type=record.record_type,
                source_id=record.source_id,
                target_id=target_id,
                action=action,
                reason=reason,
                blocking=blocking,
                conflict_summary=summary,
            )
        )
    digest = hashlib.sha256()
    digest.update(canonical_manifest_json(manifest))
    digest.update(str(context.workspace_id).encode())
    digest.update(mode.value.encode())
    digest.update(idempotency_key.strip().encode())
    manifest_fingerprint = hashlib.sha256(
        canonical_manifest_json(manifest)
    ).hexdigest()
    return RestorePreview(
        preview_id=digest.hexdigest(),
        manifest_fingerprint=manifest_fingerprint,
        mode=mode,
        target_workspace_id=target_workspace_id,
        items=tuple(items),
        blocked=any(item.blocking for item in items),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("restore datetime must include timezone")
    return parsed


def _required_datetime(value: Any) -> datetime:
    parsed = _parse_datetime(value)
    if parsed is None:
        raise ValueError("restore datetime is required")
    return parsed


def _restored_fingerprint(
    workspace_id: UUID,
    record_type: RecordType,
    source_id: UUID,
) -> str:
    return hashlib.sha256(
        f"{workspace_id}:{record_type.value}:{source_id}:read-only".encode()
    ).hexdigest()


def _new_instance(
    record: PortableRecord,
    data: dict[str, Any],
    workspace_id: UUID,
) -> Any:
    if record.record_type is RecordType.PLATFORM_ACCOUNT:
        return PlatformAccount(
            workspace_id=workspace_id,
            platform=_required_platform(record),
            name=str(data["name"]),
        )
    if record.record_type is RecordType.OBJECTIVE_PROFILE:
        return ObjectiveProfile(
            workspace_id=workspace_id,
            account_id=UUID(data["account_id"]),
            version=int(data["version"]),
            objectives=list(data["objectives"]),
            metric_weights=dict(data["metric_weights"]),
            is_account_default=bool(data["is_account_default"]),
        )
    if record.record_type is RecordType.BENCHMARK_PROFILE:
        return BenchmarkProfile(
            workspace_id=workspace_id,
            account_id=UUID(data["account_id"]),
            version=int(data["version"]),
            sample_size=int(data["sample_size"]),
            is_account_default=bool(data["is_account_default"]),
        )
    if record.record_type is RecordType.COLUMN_CAMPAIGN:
        return ColumnCampaign(
            workspace_id=workspace_id,
            account_id=UUID(data["account_id"]),
            name=str(data["name"]),
            kind=ColumnCampaignKind(data["kind"]),
            starts_at=_parse_datetime(data.get("starts_at")),
            ends_at=_parse_datetime(data.get("ends_at")),
            objective_profile_id=(
                UUID(data["objective_profile_id"])
                if data.get("objective_profile_id")
                else None
            ),
            benchmark_profile_id=(
                UUID(data["benchmark_profile_id"])
                if data.get("benchmark_profile_id")
                else None
            ),
        )
    if record.record_type is RecordType.METRIC_DEFINITION:
        return MetricDefinition(
            workspace_id=workspace_id,
            platform=_required_platform(record),
            content_type=ContentType(data["content_type"]),
            key=str(data["key"]),
            label=str(data["label"]),
            unit=MetricUnit(data["unit"]),
            aggregation=MetricAggregation(data["aggregation"]),
            higher_is_better=bool(data["higher_is_better"]),
            is_default=bool(data["is_default"]),
        )
    if record.record_type is RecordType.CONTENT:
        return Content(
            workspace_id=workspace_id,
            account_id=UUID(data["account_id"]),
            platform=_required_platform(record),
            title=str(data["title"]),
            body=str(data["body"]),
            objective_profile_id=UUID(data["objective_profile_id"]),
            benchmark_profile_id=UUID(data["benchmark_profile_id"]),
            content_type=ContentType(data["content_type"]),
            column_campaign_id=(
                UUID(data["column_campaign_id"])
                if data.get("column_campaign_id")
                else None
            ),
            work_url=data.get("work_url"),
            platform_content_id=data.get("platform_content_id"),
            status=ContentStatus(data["status"]),
            published_title=data.get("published_title"),
            published_body=data.get("published_body"),
            published_at=_parse_datetime(data.get("published_at")),
            deleted_at=_parse_datetime(data.get("deleted_at")),
        )
    if record.record_type is RecordType.DATA_SNAPSHOT:
        return DataSnapshot(
            workspace_id=workspace_id,
            content_id=UUID(data["content_id"]),
            account_id=UUID(data["account_id"]),
            platform=_required_platform(record),
            content_type=ContentType(data["content_type"]),
            collected_at=_required_datetime(data["collected_at"]),
            age_seconds=int(data["age_seconds"]),
            maturity_bucket=str(data["maturity_bucket"]),
            source=SnapshotSource(data["source"]),
            confirmed=bool(data["confirmed"]),
            confirmed_at=_parse_datetime(data.get("confirmed_at")),
            confirmed_by=None,
            original_screenshot_asset_id=None,
        )
    if record.record_type is RecordType.SNAPSHOT_METRIC_VALUE:
        return SnapshotMetricValue(
            workspace_id=workspace_id,
            snapshot_id=UUID(data["snapshot_id"]),
            metric_key=str(data["metric_key"]),
            raw_value=(
                Decimal(str(data["raw_value"]))
                if data.get("raw_value") is not None
                else None
            ),
            normalized_value=(
                Decimal(str(data["normalized_value"]))
                if data.get("normalized_value") is not None
                else None
            ),
            ocr_confidence=(
                float(data["ocr_confidence"])
                if data.get("ocr_confidence") is not None
                else None
            ),
            eligible_for_benchmark=bool(data["eligible_for_benchmark"]),
            metric_definition_id=(
                UUID(data["metric_definition_id"])
                if data.get("metric_definition_id")
                else None
            ),
        )
    if record.record_type is RecordType.STYLE_PROFILE:
        return AccountStyleProfile(
            workspace_id=workspace_id,
            account_id=UUID(data["account_id"]),
            scope_key=str(data["scope_key"]),
            version=int(data["version"]),
            status=StyleProfileStatus(data["status"]),
            style=dict(data["style"]),
            sample_content_ids=[
                str(item) for item in data["sample_content_ids"]
            ],
            diff=dict(data["diff"]),
            column_campaign_id=(
                UUID(data["column_campaign_id"])
                if data.get("column_campaign_id")
                else None
            ),
            base_profile_id=(
                UUID(data["base_profile_id"])
                if data.get("base_profile_id")
                else None
            ),
            created_by=None,
            confirmed_by=None,
            confirmed_at=_parse_datetime(data.get("confirmed_at")),
        )
    if record.record_type is RecordType.STYLE_SAMPLE:
        return StyleSample(
            workspace_id=workspace_id,
            account_id=UUID(data["account_id"]),
            scope_key=str(data["scope_key"]),
            content_id=UUID(data["content_id"]),
            column_campaign_id=(
                UUID(data["column_campaign_id"])
                if data.get("column_campaign_id")
                else None
            ),
            selected_by=None,
            selected_at=_required_datetime(data["selected_at"]),
        )
    if record.record_type is RecordType.FACT_SOURCE_METADATA:
        return FactSource(
            workspace_id=workspace_id,
            kind=FactSourceKind(data["kind"]),
            level=FactSourceLevel(data["level"]),
            title=str(data["title"]),
            status=FactSourceStatus(data["status"]),
            created_by=None,
            source_url=data.get("source_url"),
            resolved_ips=[],
            file_name=data.get("file_name"),
            mime_type=data.get("mime_type"),
            size=data.get("size"),
            content_sha256=None,
            raw_content=None,
            source_text=None,
            published_at=_parse_datetime(data.get("published_at")),
            accessed_at=_parse_datetime(data.get("accessed_at")),
            untrusted_data=bool(data["untrusted_data"]),
            status_detail={},
        )
    if record.record_type is RecordType.FACT_ITEM:
        return FactItem(
            workspace_id=workspace_id,
            source_id=UUID(data["source_id"]),
            field_name=str(data["field_name"]),
            field_code=str(data["field_code"]),
            value=str(data["value"]),
            source_location=str(data["source_location"]),
            confidence=float(data["confidence"]),
            status=FactItemStatus(data["status"]),
            conflict_status=FactConflictStatus(data["conflict_status"]),
            confirmed_by=None,
            confirmed_at=_parse_datetime(data.get("confirmed_at")),
            override_record=None,
        )
    if record.record_type is RecordType.RISK_DOCUMENT_METADATA:
        return RiskDocument(
            workspace_id=workspace_id,
            platform=_required_platform(record),
            scope=RiskDocumentScope.PRIVATE,
            source_level=RiskSourceLevel(data["source_level"]),
            title=str(data["title"]),
            authorization_status=RiskAuthorizationStatus(
                data["authorization_status"]
            ),
            status=RiskDocumentStatus(data["status"]),
            version=int(data["version"]),
            source_url=data.get("source_url"),
            private_document_id=data.get("private_document_id"),
            published_at=_parse_datetime(data.get("published_at")),
            effective_at=_parse_datetime(data.get("effective_at")),
            accessed_at=_parse_datetime(data.get("accessed_at")),
            reviewed_by=None,
            previous_version_id=(
                UUID(data["previous_version_id"])
                if data.get("previous_version_id")
                else None
            ),
            file_name=data.get("file_name"),
            mime_type=data.get("mime_type"),
            object_key=None,
            content_sha256=None,
            resolved_ips=[],
            untrusted_data=bool(data["untrusted_data"]),
            redistribution_authorized=bool(
                data["redistribution_authorized"]
            ),
        )
    if record.record_type is RecordType.AGENT_BRIEFING:
        return AgentBriefing(
            workspace_id=workspace_id,
            input_fingerprint=_restored_fingerprint(
                workspace_id,
                record.record_type,
                record.source_id,
            ),
            algorithm_version=str(data["algorithm_version"]),
            tool_catalog_version=str(data["tool_catalog_version"]),
            candidates=[],
            priority_candidate=None,
            data_cutoff_at=_required_datetime(data["data_cutoff_at"]),
        )
    if record.record_type is RecordType.AGENT_PLAN:
        fingerprint = _restored_fingerprint(
            workspace_id,
            record.record_type,
            record.source_id,
        )
        approval_snapshot = AgentPlanApprovalSnapshot(
            briefing_input_fingerprint=fingerprint,
            account_configuration_version=fingerprint,
            model_configuration_version=fingerprint,
            risk_rule_version=fingerprint,
        )
        document = StoredAgentPlanDocument(
            plan=AgentPlanDocument(
                goal="已恢复的历史智能体记录（只读，不可执行）",
                platform=_required_platform(record),
                account_id=UUID(str(data["account_id"])),
                candidate_id=f"restored-{record.source_id}",
                input_fingerprint=fingerprint,
                tool_catalog_version=str(data["tool_catalog_version"]),
                steps=(
                    AgentPlanStep(
                        step_index=0,
                        tool_name="restored_history",
                        tool_version="1.0.0",
                        arguments={},
                        rationale="轻量备份不包含原始参数，恢复后仅供审计查看。",
                    ),
                ),
            ),
            approval_snapshot=approval_snapshot,
        )
        plan = AgentPlan(
            workspace_id=workspace_id,
            briefing_id=UUID(str(data["briefing_id"])),
            account_id=UUID(str(data["account_id"])),
            platform=_required_platform(record),
            idempotency_key=f"restored-history:{record.source_id}",
            input_fingerprint=fingerprint,
            tool_catalog_version=str(data["tool_catalog_version"]),
            document=document.model_dump(mode="json"),
            plan_fingerprint=fingerprint,
            status=AgentPlanStatus.INVALIDATED,
            created_by=None,
            approved_by=None,
            approved_at=None,
        )
        plan.created_at = _required_datetime(data["created_at"])
        return plan
    if record.record_type is RecordType.AGENT_RUN:
        run = AgentRun(
            workspace_id=workspace_id,
            plan_id=UUID(str(data["plan_id"])),
            account_id=UUID(str(data["account_id"])),
            platform=_required_platform(record),
            status=AgentRunStatus.CANCELLED,
            current_step_index=0,
            operation_version=1,
            created_by=None,
            claim_token=None,
            lease_expires_at=None,
            safe_error_code="AGENT_HISTORY_RESTORED_READ_ONLY",
            completed_at=(
                _parse_datetime(data.get("completed_at"))
                or _required_datetime(data["created_at"])
            ),
        )
        run.created_at = _required_datetime(data["created_at"])
        return run
    if record.record_type is RecordType.AGENT_STEP:
        completed_at = (
            _parse_datetime(data.get("completed_at"))
            or datetime(1970, 1, 1, tzinfo=UTC)
        )
        return AgentRunStep(
            workspace_id=workspace_id,
            run_id=UUID(str(data["run_id"])),
            step_index=int(data["step_index"]),
            tool_name=str(data["tool_name"]),
            tool_version=str(data["tool_version"]),
            tool_risk=AgentToolRisk(data["tool_risk"]),
            input_fingerprint=_restored_fingerprint(
                workspace_id,
                record.record_type,
                record.source_id,
            ),
            input_envelope={"restored_history": True, "arguments": {}},
            status=AgentStepStatus.CANCELLED,
            operation_version=1,
            attempt_count=int(data["attempt_count"]),
            result_envelope={"restored_history": True},
            safe_error_code="AGENT_HISTORY_RESTORED_READ_ONLY",
            started_at=None,
            completed_at=completed_at,
        )
    if record.record_type is RecordType.AGENT_ARTIFACT:
        return AgentArtifact(
            workspace_id=workspace_id,
            run_id=UUID(str(data["run_id"])),
            kind=AgentArtifactKind(data["kind"]),
            resource_type=str(data["resource_type"]),
            resource_id=uuid5(
                workspace_id,
                (
                    "restored-agent-resource:"
                    f"{data['resource_type']}:{data['resource_id']}"
                ),
            ),
            step_id=(
                UUID(str(data["step_id"])) if data.get("step_id") else None
            ),
            safe_metadata={
                **dict(data["safe_metadata"]),
                "restored_read_only": True,
            },
        )
    if record.record_type is RecordType.AGENT_EVENT:
        event = AgentEvent(
            workspace_id=workspace_id,
            event_type=str(data["event_type"]),
            idempotency_key=f"restored-agent-event:{record.source_id}",
            safe_payload={
                **dict(data["safe_payload"]),
                "restored_read_only": True,
            },
            run_id=(
                UUID(str(data["run_id"])) if data.get("run_id") else None
            ),
            step_id=(
                UUID(str(data["step_id"])) if data.get("step_id") else None
            ),
            actor_id=None,
        )
        event.created_at = _required_datetime(data["created_at"])
        return event
    raise ValueError("unsupported restore record")


def _apply_mutable_data(
    record: PortableRecord,
    instance: Any,
    data: dict[str, Any],
) -> None:
    replacement = _new_instance(record, data, instance.workspace_id)
    for field in record.data:
        setattr(instance, field, getattr(replacement, field))
    if record.platform is not None:
        instance.platform = Platform(record.platform)


def apply_lightweight_restore(
    session: Session,
    context: WorkspaceContext,
    manifest: BackupManifest,
    preview: RestorePreview,
    *,
    failure_injector: Callable[[int, str], None] | None = None,
) -> None:
    if context.role != "admin":
        raise PermissionError("admin role required")
    if (
        preview.manifest_fingerprint
        != hashlib.sha256(canonical_manifest_json(manifest)).hexdigest()
    ):
        raise ValueError("restore preview does not match manifest")
    if preview.target_workspace_id is None:
        raise ValueError("restore preview has no target workspace")
    if (
        preview.mode is RestoreMode.MERGE
        and preview.target_workspace_id != context.workspace_id
    ):
        raise ValueError("restore preview target mismatch")
    if preview.blocked:
        raise ValueError("restore preview contains blocking conflicts")
    if preview.mode is RestoreMode.MERGE:
        current_preview = build_restore_preview(
            session,
            context,
            manifest,
            mode=RestoreMode.MERGE,
            idempotency_key="apply-current-state-check",
        )
        current_items = {
            (item.record_type, item.source_id): (
                item.target_id,
                item.action,
                item.reason,
                item.blocking,
            )
            for item in current_preview.items
        }
        submitted_items = {
            (item.record_type, item.source_id): (
                item.target_id,
                item.action,
                item.reason,
                item.blocking,
            )
            for item in preview.items
        }
        if current_items != submitted_items:
            raise ValueError("restore preview is stale")
    elif session.get(Workspace, preview.target_workspace_id) is not None and any(
        item.action is RestoreAction.CREATE
        for item in preview.items
        if item.record_type is not RecordType.ASSET_REFERENCE
    ):
        raise ValueError("restore preview is stale")
    preview_by_source = {
        (item.record_type, item.source_id): item for item in preview.items
    }
    manifest_identities = {
        (record.record_type, record.source_id) for record in manifest.records
    }
    if manifest_identities != set(preview_by_source):
        raise ValueError("restore preview does not match manifest")

    target_workspace_id = preview.target_workspace_id
    records = sorted(
        manifest.records,
        key=lambda item: (
            APPLY_ORDER[item.record_type],
            int(item.data.get("version", 0)),
            str(item.source_id),
        ),
    )
    actions = {
        (item.record_type, item.source_id): item.action for item in preview.items
    }
    write_index = 0
    with session.begin_nested():
        if preview.mode is RestoreMode.NEW:
            target_workspace = session.get(Workspace, target_workspace_id)
            if target_workspace is None:
                target_workspace = Workspace(
                    name=f"{manifest.workspace.name}（恢复）"[:120]
                )
                target_workspace.id = target_workspace_id
                session.add(target_workspace)
                session.flush()
                source_member = session.get(WorkspaceMember, context.member_id)
                if (
                    source_member is None
                    or source_member.workspace_id != context.workspace_id
                ):
                    raise PermissionError("restoring member is unavailable")
                target_member = WorkspaceMember(
                    workspace_id=target_workspace_id,
                    display_name=source_member.display_name,
                    role=MemberRole.ADMIN,
                    revoked_at=None,
                )
                target_member.id = uuid5(
                    target_workspace_id,
                    "lightweight-restore-admin",
                )
                session.add(target_member)
                session.flush()
        for record in records:
            action = actions[(record.record_type, record.source_id)]
            if action is RestoreAction.SKIP:
                continue
            if action is RestoreAction.CONFLICT:
                raise ValueError("restore conflict cannot be applied")
            data = _mapped_data(record, manifest, target_workspace_id)
            target_id = _target_id(target_workspace_id, manifest, record)
            model = MODEL_BY_TYPE[record.record_type]
            instance = session.get(cast(Any, model), target_id)
            if action is RestoreAction.CREATE:
                if instance is not None:
                    raise ValueError("restore target appeared after preview")
                instance = _new_instance(record, data, target_workspace_id)
                instance.id = target_id
                session.add(instance)
            elif action is RestoreAction.OVERWRITE:
                if instance is None or instance.workspace_id != target_workspace_id:
                    raise ValueError("restore overwrite target changed")
                _apply_mutable_data(record, instance, data)
            session.flush()
            write_index += 1
            if failure_injector is not None:
                failure_injector(write_index, record.record_type.value)

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import (
    BenchmarkProfile,
    ColumnCampaign,
    ObjectiveProfile,
    PlatformAccount,
)
from app.modules.content.models import Content, ContentAsset
from app.modules.exports.manifest import (
    BACKUP_PRODUCT_VERSION,
    BACKUP_SCHEMA_VERSION,
    BackupManifest,
    PortableRecord,
    RecordType,
    WorkspaceBackup,
    canonical_manifest_json,
)
from app.modules.metrics.models import (
    DataSnapshot,
    MetricDefinition,
    SnapshotMetricValue,
)
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentBriefing,
    AgentEvent,
    AgentPlan,
    AgentRun,
    AgentRunStep,
)
from app.modules.risk_rag.models import RiskDocument, RiskDocumentScope
from app.modules.style_facts.fact_models import FactItem, FactSource
from app.modules.style_facts.style_models import AccountStyleProfile, StyleSample
from app.modules.workspace.models import Workspace


def _portable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("backup datetime must include timezone")
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _portable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_portable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _data(**values: Any) -> dict[str, Any]:
    return {key: _portable(value) for key, value in values.items()}


def _record(
    record_type: RecordType,
    record_id,
    *,
    platform=None,
    **data: Any,
) -> PortableRecord:
    return PortableRecord(
        record_type=record_type,
        source_id=record_id,
        platform=_portable(platform) if platform is not None else None,
        data=_data(**data),
    )


def _safe_agent_artifact_metadata(
    value: dict[str, object],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("publication_performed", "approval_exclusion"):
        item = value.get(key)
        if isinstance(item, bool):
            result[key] = item
    recommendation = value.get("recommendation")
    if isinstance(recommendation, dict):
        allowed = {
            "source",
            "layout",
            "preserve_account_style",
            "requires_human_review",
        }
        result["recommendation"] = {
            str(key): item
            for key, item in recommendation.items()
            if key in allowed and isinstance(item, (str, bool))
        }
    return result


def _safe_agent_event_payload(
    value: dict[str, object],
) -> dict[str, object]:
    allowed = {
        "run_id",
        "confirmation_id",
        "tool_name",
        "tool_version",
        "status",
        "error_code",
        "decision",
        "publication_performed",
        "scope",
    }
    return {
        str(key): item
        for key, item in value.items()
        if key in allowed
        and (
            item is None
            or isinstance(item, (str, int, float, bool))
        )
    }


def build_lightweight_manifest(
    session: Session,
    context: WorkspaceContext,
    *,
    exported_at: datetime | None = None,
) -> BackupManifest:
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == context.workspace_id)
    )
    if workspace is None:
        raise LookupError("workspace not found")
    records: list[PortableRecord] = []

    accounts = list(
        session.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.workspace_id == context.workspace_id)
            .order_by(PlatformAccount.id)
        )
    )
    for account in accounts:
        records.append(
            _record(
                RecordType.PLATFORM_ACCOUNT,
                account.id,
                platform=account.platform,
                name=account.name,
            )
        )
    for objective_profile in session.scalars(
        select(ObjectiveProfile)
        .where(ObjectiveProfile.workspace_id == context.workspace_id)
        .order_by(ObjectiveProfile.id)
    ):
        records.append(
            _record(
                RecordType.OBJECTIVE_PROFILE,
                objective_profile.id,
                account_id=objective_profile.account_id,
                version=objective_profile.version,
                objectives=objective_profile.objectives,
                metric_weights=objective_profile.metric_weights,
                is_account_default=objective_profile.is_account_default,
            )
        )
    for benchmark_profile in session.scalars(
        select(BenchmarkProfile)
        .where(BenchmarkProfile.workspace_id == context.workspace_id)
        .order_by(BenchmarkProfile.id)
    ):
        records.append(
            _record(
                RecordType.BENCHMARK_PROFILE,
                benchmark_profile.id,
                account_id=benchmark_profile.account_id,
                version=benchmark_profile.version,
                sample_size=benchmark_profile.sample_size,
                is_account_default=benchmark_profile.is_account_default,
            )
        )
    for campaign in session.scalars(
        select(ColumnCampaign)
        .where(ColumnCampaign.workspace_id == context.workspace_id)
        .order_by(ColumnCampaign.id)
    ):
        records.append(
            _record(
                RecordType.COLUMN_CAMPAIGN,
                campaign.id,
                account_id=campaign.account_id,
                name=campaign.name,
                kind=campaign.kind,
                starts_at=campaign.starts_at,
                ends_at=campaign.ends_at,
                objective_profile_id=campaign.objective_profile_id,
                benchmark_profile_id=campaign.benchmark_profile_id,
            )
        )
    for definition in session.scalars(
        select(MetricDefinition)
        .where(MetricDefinition.workspace_id == context.workspace_id)
        .order_by(MetricDefinition.id)
    ):
        records.append(
            _record(
                RecordType.METRIC_DEFINITION,
                definition.id,
                platform=definition.platform,
                content_type=definition.content_type,
                key=definition.key,
                label=definition.label,
                unit=definition.unit,
                aggregation=definition.aggregation,
                higher_is_better=definition.higher_is_better,
                is_default=definition.is_default,
            )
        )
    for content in session.scalars(
        select(Content)
        .where(Content.workspace_id == context.workspace_id)
        .order_by(Content.id)
    ):
        records.append(
            _record(
                RecordType.CONTENT,
                content.id,
                platform=content.platform,
                account_id=content.account_id,
                objective_profile_id=content.objective_profile_id,
                benchmark_profile_id=content.benchmark_profile_id,
                content_type=content.content_type,
                column_campaign_id=content.column_campaign_id,
                title=content.title,
                body=content.body,
                work_url=content.work_url,
                platform_content_id=content.platform_content_id,
                status=content.status,
                published_title=content.published_title,
                published_body=content.published_body,
                published_at=content.published_at,
                deleted_at=content.deleted_at,
            )
        )
    for asset in session.scalars(
        select(ContentAsset)
        .where(ContentAsset.workspace_id == context.workspace_id)
        .order_by(ContentAsset.id)
    ):
        records.append(
            _record(
                RecordType.ASSET_REFERENCE,
                asset.id,
                content_id=asset.content_id,
                category=asset.category,
                file_name=asset.file_name,
                mime_type=asset.mime_type,
                size=asset.size,
            )
        )
    for snapshot in session.scalars(
        select(DataSnapshot)
        .where(DataSnapshot.workspace_id == context.workspace_id)
        .order_by(DataSnapshot.id)
    ):
        records.append(
            _record(
                RecordType.DATA_SNAPSHOT,
                snapshot.id,
                platform=snapshot.platform,
                content_id=snapshot.content_id,
                account_id=snapshot.account_id,
                content_type=snapshot.content_type,
                collected_at=snapshot.collected_at,
                age_seconds=snapshot.age_seconds,
                maturity_bucket=snapshot.maturity_bucket,
                source=snapshot.source,
                confirmed=snapshot.confirmed,
                confirmed_at=snapshot.confirmed_at,
                original_screenshot_asset_id=snapshot.original_screenshot_asset_id,
            )
        )
    for value in session.scalars(
        select(SnapshotMetricValue)
        .where(SnapshotMetricValue.workspace_id == context.workspace_id)
        .order_by(SnapshotMetricValue.id)
    ):
        records.append(
            _record(
                RecordType.SNAPSHOT_METRIC_VALUE,
                value.id,
                snapshot_id=value.snapshot_id,
                metric_key=value.metric_key,
                raw_value=value.raw_value,
                normalized_value=value.normalized_value,
                ocr_confidence=value.ocr_confidence,
                eligible_for_benchmark=value.eligible_for_benchmark,
                metric_definition_id=value.metric_definition_id,
            )
        )
    for profile in session.scalars(
        select(AccountStyleProfile)
        .where(AccountStyleProfile.workspace_id == context.workspace_id)
        .order_by(AccountStyleProfile.version, AccountStyleProfile.id)
    ):
        account = next(
            item for item in accounts if item.id == profile.account_id
        )
        records.append(
            _record(
                RecordType.STYLE_PROFILE,
                profile.id,
                platform=account.platform,
                account_id=profile.account_id,
                scope_key=profile.scope_key,
                version=profile.version,
                status=profile.status,
                style=profile.style,
                sample_content_ids=profile.sample_content_ids,
                diff=profile.diff,
                column_campaign_id=profile.column_campaign_id,
                base_profile_id=profile.base_profile_id,
                confirmed_at=profile.confirmed_at,
            )
        )
    for sample in session.scalars(
        select(StyleSample)
        .where(StyleSample.workspace_id == context.workspace_id)
        .order_by(StyleSample.id)
    ):
        account = next(
            item for item in accounts if item.id == sample.account_id
        )
        records.append(
            _record(
                RecordType.STYLE_SAMPLE,
                sample.id,
                platform=account.platform,
                account_id=sample.account_id,
                scope_key=sample.scope_key,
                content_id=sample.content_id,
                column_campaign_id=sample.column_campaign_id,
                selected_at=sample.selected_at,
            )
        )
    for source in session.scalars(
        select(FactSource)
        .where(FactSource.workspace_id == context.workspace_id)
        .order_by(FactSource.id)
    ):
        records.append(
            _record(
                RecordType.FACT_SOURCE_METADATA,
                source.id,
                kind=source.kind,
                level=source.level,
                title=source.title,
                status=source.status,
                source_url=source.source_url,
                file_name=source.file_name,
                mime_type=source.mime_type,
                size=source.size,
                published_at=source.published_at,
                accessed_at=source.accessed_at,
                untrusted_data=source.untrusted_data,
            )
        )
    for item in session.scalars(
        select(FactItem)
        .where(FactItem.workspace_id == context.workspace_id)
        .order_by(FactItem.id)
    ):
        records.append(
            _record(
                RecordType.FACT_ITEM,
                item.id,
                source_id=item.source_id,
                field_name=item.field_name,
                field_code=item.field_code,
                value=item.value,
                source_location=item.source_location,
                confidence=item.confidence,
                status=item.status,
                conflict_status=item.conflict_status,
                confirmed_at=item.confirmed_at,
            )
        )
    risk_documents = list(
        session.scalars(
            select(RiskDocument)
            .where(
                RiskDocument.workspace_id == context.workspace_id,
                RiskDocument.scope == RiskDocumentScope.PRIVATE,
            )
            .order_by(RiskDocument.version, RiskDocument.id)
        )
    )
    risk_document_ids = {document.id for document in risk_documents}
    for document in risk_documents:
        records.append(
            _record(
                RecordType.RISK_DOCUMENT_METADATA,
                document.id,
                platform=document.platform,
                scope=document.scope,
                source_level=document.source_level,
                title=document.title,
                authorization_status=document.authorization_status,
                status=document.status,
                version=document.version,
                source_url=document.source_url,
                private_document_id=document.private_document_id,
                published_at=document.published_at,
                effective_at=document.effective_at,
                accessed_at=document.accessed_at,
                previous_version_id=(
                    document.previous_version_id
                    if document.previous_version_id in risk_document_ids
                    else None
                ),
                file_name=document.file_name,
                mime_type=document.mime_type,
                untrusted_data=document.untrusted_data,
                redistribution_authorized=document.redistribution_authorized,
            )
        )
    for briefing in session.scalars(
        select(AgentBriefing)
        .where(AgentBriefing.workspace_id == context.workspace_id)
        .order_by(AgentBriefing.created_at, AgentBriefing.id)
    ):
        records.append(
            _record(
                RecordType.AGENT_BRIEFING,
                briefing.id,
                algorithm_version=briefing.algorithm_version,
                tool_catalog_version=briefing.tool_catalog_version,
                data_cutoff_at=briefing.data_cutoff_at,
            )
        )
    for plan in session.scalars(
        select(AgentPlan)
        .where(AgentPlan.workspace_id == context.workspace_id)
        .order_by(AgentPlan.created_at, AgentPlan.id)
    ):
        records.append(
            _record(
                RecordType.AGENT_PLAN,
                plan.id,
                platform=plan.platform,
                briefing_id=plan.briefing_id,
                account_id=plan.account_id,
                original_status=plan.status,
                tool_catalog_version=plan.tool_catalog_version,
                created_at=plan.created_at,
            )
        )
    for run in session.scalars(
        select(AgentRun)
        .where(AgentRun.workspace_id == context.workspace_id)
        .order_by(AgentRun.created_at, AgentRun.id)
    ):
        records.append(
            _record(
                RecordType.AGENT_RUN,
                run.id,
                platform=run.platform,
                plan_id=run.plan_id,
                account_id=run.account_id,
                original_status=run.status,
                safe_error_code=run.safe_error_code,
                completed_at=run.completed_at,
                created_at=run.created_at,
            )
        )
    for step in session.scalars(
        select(AgentRunStep)
        .where(AgentRunStep.workspace_id == context.workspace_id)
        .order_by(AgentRunStep.run_id, AgentRunStep.step_index)
    ):
        records.append(
            _record(
                RecordType.AGENT_STEP,
                step.id,
                run_id=step.run_id,
                step_index=step.step_index,
                tool_name=step.tool_name,
                tool_version=step.tool_version,
                tool_risk=step.tool_risk,
                original_status=step.status,
                attempt_count=step.attempt_count,
                safe_error_code=step.safe_error_code,
                completed_at=step.completed_at,
            )
        )
    for artifact in session.scalars(
        select(AgentArtifact)
        .where(AgentArtifact.workspace_id == context.workspace_id)
        .order_by(AgentArtifact.created_at, AgentArtifact.id)
    ):
        records.append(
            _record(
                RecordType.AGENT_ARTIFACT,
                artifact.id,
                run_id=artifact.run_id,
                step_id=artifact.step_id,
                kind=artifact.kind,
                resource_type=artifact.resource_type,
                resource_id=artifact.resource_id,
                safe_metadata=_safe_agent_artifact_metadata(
                    artifact.safe_metadata
                ),
            )
        )
    for event in session.scalars(
        select(AgentEvent)
        .where(AgentEvent.workspace_id == context.workspace_id)
        .order_by(AgentEvent.created_at, AgentEvent.id)
    ):
        records.append(
            _record(
                RecordType.AGENT_EVENT,
                event.id,
                run_id=event.run_id,
                step_id=event.step_id,
                event_type=event.event_type,
                safe_payload=_safe_agent_event_payload(event.safe_payload),
                created_at=event.created_at,
            )
        )
    records.sort(key=lambda item: (item.record_type.value, str(item.source_id)))
    return BackupManifest(
        schema_version=BACKUP_SCHEMA_VERSION,
        product_version=BACKUP_PRODUCT_VERSION,
        exported_at=exported_at or datetime.now(UTC),
        workspace=WorkspaceBackup(source_id=workspace.id, name=workspace.name),
        records=tuple(records),
    )


def render_lightweight_json(
    session: Session,
    context: WorkspaceContext,
    *,
    exported_at: datetime | None = None,
) -> bytes:
    return canonical_manifest_json(
        build_lightweight_manifest(
            session,
            context,
            exported_at=exported_at,
        )
    )

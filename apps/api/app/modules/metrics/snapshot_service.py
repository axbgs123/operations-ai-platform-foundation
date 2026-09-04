from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.analytics.events import EventName, EventService, ProductEventInput
from app.modules.content.models import AssetCategory, Content, ContentAsset
from app.modules.metrics.definitions import validate_metric_values
from app.modules.metrics.maturity import SnapshotCompleteness, bucket_for_age, calculate_completeness
from app.modules.metrics.models import (
    DataSnapshot,
    MetricDefinition,
    MetricOutboxEvent,
    SnapshotMetricValue,
    SnapshotSource,
)
from app.modules.metrics.schemas import SnapshotMetricInput
from app.modules.workspace.permissions import Permission, require_permission


MIN_OCR_CONFIDENCE = 0.8


class SnapshotService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _content(self, content_id: UUID) -> Content:
        content = self._session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == self._context.workspace_id,
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise LookupError("content not found")
        return content

    def _snapshot(self, content_id: UUID, snapshot_id: UUID) -> DataSnapshot:
        snapshot = self._session.scalar(
            select(DataSnapshot).where(
                DataSnapshot.id == snapshot_id,
                DataSnapshot.content_id == content_id,
                DataSnapshot.workspace_id == self._context.workspace_id,
            )
        )
        if snapshot is None:
            raise LookupError("snapshot not found")
        return snapshot

    def _custom_definitions(self, content: Content) -> list[MetricDefinition]:
        return list(
            self._session.scalars(
                select(MetricDefinition).where(
                    MetricDefinition.workspace_id == self._context.workspace_id,
                    MetricDefinition.platform == content.platform,
                    MetricDefinition.content_type == content.content_type,
                )
            )
        )

    def create(
        self,
        content_id: UUID,
        *,
        collected_at: datetime,
        source: SnapshotSource,
        metrics: list[SnapshotMetricInput],
        original_screenshot_asset_id: UUID | None,
        analytics_eligible: bool = True,
    ) -> DataSnapshot:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        content = self._content(content_id)
        if content.published_at is None:
            raise ValueError("content must be published before collecting metrics")
        collected_at = collected_at.astimezone(UTC)
        age = collected_at - content.published_at
        maturity_bucket = bucket_for_age(age)

        if original_screenshot_asset_id is not None:
            asset = self._session.scalar(
                select(ContentAsset).where(
                    ContentAsset.id == original_screenshot_asset_id,
                    ContentAsset.content_id == content.id,
                    ContentAsset.workspace_id == self._context.workspace_id,
                    ContentAsset.category == AssetCategory.SCREENSHOT,
                )
            )
            if asset is None:
                raise ValueError("screenshot asset must belong to the content")

        raw_values = {metric.key: metric.raw_value for metric in metrics}
        custom_definitions = self._custom_definitions(content)
        validated = validate_metric_values(
            content.platform,
            content.content_type,
            raw_values,
            custom_definitions=custom_definitions,
        )
        snapshot = DataSnapshot(
            workspace_id=self._context.workspace_id,
            content_id=content.id,
            account_id=content.account_id,
            platform=content.platform,
            content_type=content.content_type,
            collected_at=collected_at,
            age_seconds=int(age.total_seconds()),
            maturity_bucket=maturity_bucket.value,
            source=source,
            analytics_eligible=analytics_eligible,
            original_screenshot_asset_id=original_screenshot_asset_id,
        )
        self._session.add(snapshot)
        self._session.flush()

        custom_by_key = {
            definition.key: definition for definition in custom_definitions
        }
        confidence_required = source in {
            SnapshotSource.SCREENSHOT,
            SnapshotSource.EXTENSION,
        }
        for metric in metrics:
            normalized = validated[metric.key]
            if confidence_required and (
                metric.ocr_confidence is None
                or metric.ocr_confidence < MIN_OCR_CONFIDENCE
            ):
                normalized = None
            self._session.add(
                SnapshotMetricValue(
                    workspace_id=self._context.workspace_id,
                    snapshot_id=snapshot.id,
                    metric_key=metric.key,
                    raw_value=(
                        Decimal(str(metric.raw_value))
                        if metric.raw_value is not None
                        else None
                    ),
                    normalized_value=(
                        Decimal(str(normalized)) if normalized is not None else None
                    ),
                    ocr_confidence=metric.ocr_confidence,
                    metric_definition_id=(
                        custom_by_key[metric.key].id
                        if metric.key in custom_by_key
                        else None
                    ),
                )
            )
        self._session.flush()
        EventService(self._session, self._context).record(
            ProductEventInput(
                event_name=EventName.COLLECTION_STARTED,
                idempotency_key=f"collection-started:{snapshot.id}",
                account_id=snapshot.account_id,
                content_id=snapshot.content_id,
                properties={
                    "source": {
                        SnapshotSource.MANUAL: "manual",
                        SnapshotSource.TABULAR_IMPORT: "xlsx",
                        SnapshotSource.SCREENSHOT: "screenshot",
                        SnapshotSource.EXTENSION: "extension",
                        SnapshotSource.PUBLIC_API: "public_api",
                    }[snapshot.source]
                },
                provider_mode="real" if analytics_eligible else "mock",
            )
        )
        return snapshot

    def read(self, content_id: UUID, snapshot_id: UUID) -> DataSnapshot:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._content(content_id)
        return self._snapshot(content_id, snapshot_id)

    def list_snapshots(self, content_id: UUID) -> list[DataSnapshot]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        self._content(content_id)
        return list(
            self._session.scalars(
                select(DataSnapshot)
                .where(
                    DataSnapshot.content_id == content_id,
                    DataSnapshot.workspace_id == self._context.workspace_id,
                )
                .order_by(DataSnapshot.collected_at, DataSnapshot.created_at)
            )
        )

    def values(self, snapshot_id: UUID) -> list[SnapshotMetricValue]:
        return list(
            self._session.scalars(
                select(SnapshotMetricValue)
                .where(
                    SnapshotMetricValue.snapshot_id == snapshot_id,
                    SnapshotMetricValue.workspace_id == self._context.workspace_id,
                )
                .order_by(SnapshotMetricValue.created_at)
            )
        )

    def completeness(self, content_id: UUID) -> SnapshotCompleteness:
        snapshots = self.list_snapshots(content_id)
        return calculate_completeness(
            timedelta(seconds=snapshot.age_seconds) for snapshot in snapshots
        )

    def read_payload(
        self,
        snapshot: DataSnapshot,
        *,
        completeness: SnapshotCompleteness | None = None,
        values: list[SnapshotMetricValue] | None = None,
    ) -> dict[str, object]:
        resolved_completeness = (
            completeness
            if completeness is not None
            else self.completeness(snapshot.content_id)
        )
        resolved_values = values if values is not None else self.values(snapshot.id)
        return {
            "id": snapshot.id,
            "workspace_id": snapshot.workspace_id,
            "content_id": snapshot.content_id,
            "platform": snapshot.platform.value,
            "content_type": snapshot.content_type.value,
            "collected_at": snapshot.collected_at,
            "age_seconds": snapshot.age_seconds,
            "maturity_bucket": snapshot.maturity_bucket,
            "source": snapshot.source.value,
            "confirmed": snapshot.confirmed,
            "confirmed_at": snapshot.confirmed_at,
            "original_screenshot_asset_id": snapshot.original_screenshot_asset_id,
            "metrics": [
                {
                    "key": value.metric_key,
                    "raw_value": value.raw_value,
                    "normalized_value": value.normalized_value,
                    "ocr_confidence": value.ocr_confidence,
                    "eligible_for_benchmark": value.eligible_for_benchmark,
                }
                for value in resolved_values
            ],
            "completeness": {
                "observed": list(resolved_completeness.observed),
                "missing": list(resolved_completeness.missing),
                "ratio": resolved_completeness.ratio,
            },
        }

    def confirm(self, content_id: UUID, snapshot_id: UUID) -> DataSnapshot:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._content(content_id)
        snapshot = self._snapshot(content_id, snapshot_id)
        if snapshot.confirmed:
            return snapshot

        snapshot.confirmed = True
        snapshot.confirmed_at = datetime.now(UTC)
        snapshot.confirmed_by = self._context.member_id
        for value in self.values(snapshot.id):
            value.eligible_for_benchmark = value.normalized_value is not None
        self._session.add(
            MetricOutboxEvent(
                workspace_id=self._context.workspace_id,
                aggregate_id=snapshot.id,
                event_type="metrics.snapshot_confirmed",
                idempotency_key=f"snapshot-confirmed:{snapshot.id}",
                payload={
                    "snapshot_id": str(snapshot.id),
                    "content_id": str(snapshot.content_id),
                    "account_id": str(snapshot.account_id),
                },
            )
        )
        EventService(self._session, self._context).record(
            ProductEventInput(
                event_name=EventName.COLLECTION_CONFIRMED,
                idempotency_key=f"collection-confirmed:{snapshot.id}",
                account_id=snapshot.account_id,
                content_id=snapshot.content_id,
                properties={
                    "source": {
                        SnapshotSource.MANUAL: "manual",
                        SnapshotSource.TABULAR_IMPORT: "xlsx",
                        SnapshotSource.SCREENSHOT: "screenshot",
                        SnapshotSource.EXTENSION: "extension",
                        SnapshotSource.PUBLIC_API: "public_api",
                    }[snapshot.source]
                },
                provider_mode=(
                    "real" if snapshot.analytics_eligible else "mock"
                ),
            )
        )
        self._session.flush()
        return snapshot

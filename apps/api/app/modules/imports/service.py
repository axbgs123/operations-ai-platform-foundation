import hashlib
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import false, func, literal, select, union_all
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.core.config import get_settings
from app.modules.content.account_models import (
    ColumnCampaign,
    Platform,
    PlatformAccount,
)
from app.modules.content.models import Content, ContentStatus
from app.modules.content.service import ContentService
from app.modules.imports.dedupe import classify_duplicate
from app.modules.imports.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportRow,
    ImportRowStatus,
    ImportSourceKind,
    ScreenshotRecognitionStatus,
)
from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.parsers.tabular import (
    normalize_manual_row,
    normalize_tabular_row,
    read_tabular,
    suggest_headers,
)
from app.modules.metrics.models import ContentType, SnapshotSource
from app.modules.metrics.schemas import SnapshotMetricInput
from app.modules.metrics.snapshot_service import SnapshotService
from app.modules.workspace.permissions import Permission, require_permission
from app.modules.imports.vision_binding import resolve_vision_binding
from app.modules.models.config_service import SecretCipher
from app.modules.workspace.models import WorkspaceMember


class ImportService:
    def __init__(self, session: Session, context: WorkspaceContext) -> None:
        self._session = session
        self._context = context

    def _account(self, account_id: UUID, platform: Platform) -> PlatformAccount:
        account = self._session.scalar(
            select(PlatformAccount).where(
                PlatformAccount.id == account_id,
                PlatformAccount.workspace_id == self._context.workspace_id,
                PlatformAccount.platform == platform,
            )
        )
        if account is None:
            raise LookupError("account not found")
        return account

    def _column(self, column_id: UUID, account_id: UUID) -> ColumnCampaign:
        column = self._session.scalar(
            select(ColumnCampaign).where(
                ColumnCampaign.id == column_id,
                ColumnCampaign.workspace_id == self._context.workspace_id,
                ColumnCampaign.account_id == account_id,
            )
        )
        if column is None:
            raise LookupError("column campaign not found")
        return column

    def _column_from_value(
        self,
        value: object,
        account_id: UUID,
    ) -> ColumnCampaign:
        try:
            column_id = UUID(str(value))
        except (TypeError, ValueError) as error:
            raise LookupError("column campaign not found") from error
        return self._column(column_id, account_id)

    def _batch(self, batch_id: UUID, *, for_update: bool = False) -> ImportBatch:
        statement = select(ImportBatch).where(
            ImportBatch.id == batch_id,
            ImportBatch.workspace_id == self._context.workspace_id,
        )
        if for_update:
            statement = statement.with_for_update()
        batch = self._session.scalar(statement)
        if batch is None:
            raise LookupError("import batch not found")
        return batch

    def rows(self, batch_id: UUID) -> list[ImportRow]:
        return list(
            self._session.scalars(
                select(ImportRow)
                .where(
                    ImportRow.batch_id == batch_id,
                    ImportRow.workspace_id == self._context.workspace_id,
                )
                .order_by(ImportRow.row_number, ImportRow.id)
            )
        )

    def read_batch(self, batch_id: UUID) -> ImportBatch:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return self._batch(batch_id)

    def history(
        self,
        *,
        platform: Platform | None,
        account_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[dict[str, object]], int]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        if account_id is not None:
            if platform is None:
                account = self._session.scalar(
                    select(PlatformAccount).where(
                        PlatformAccount.id == account_id,
                        PlatformAccount.workspace_id
                        == self._context.workspace_id,
                    )
                )
                if account is None:
                    raise LookupError("account not found")
                platform = account.platform
            else:
                self._account(account_id, platform)

        batch_query = select(
            ImportBatch.id.label("item_id"),
            literal("batch").label("item_kind"),
            ImportBatch.created_at.label("sort_time"),
        ).where(
            ImportBatch.workspace_id == self._context.workspace_id
        )
        capture_query = select(
            CaptureTask.id.label("item_id"),
            literal("capture").label("item_kind"),
            CaptureTask.collected_at.label("sort_time"),
        ).where(
            CaptureTask.workspace_id == self._context.workspace_id
        )
        if platform is not None:
            batch_query = batch_query.where(ImportBatch.platform == platform)
            capture_query = capture_query.where(CaptureTask.platform == platform)
        if account_id is not None:
            batch_query = batch_query.where(
                ImportBatch.account_id == account_id
            )
            # Capture tasks do not carry an account until Web confirmation.
            capture_query = capture_query.where(false())

        history_union = union_all(batch_query, capture_query).subquery()
        total = int(
            self._session.scalar(
                select(func.count()).select_from(history_union)
            )
            or 0
        )
        ordered = self._session.execute(
            select(
                history_union.c.item_id,
                history_union.c.item_kind,
                history_union.c.sort_time,
            )
            .order_by(
                history_union.c.sort_time.desc(),
                history_union.c.item_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        batch_ids = [
            row.item_id for row in ordered if row.item_kind == "batch"
        ]
        capture_ids = [
            row.item_id for row in ordered if row.item_kind == "capture"
        ]
        batches = {
            batch.id: batch
            for batch in self._session.scalars(
                select(ImportBatch).where(
                    ImportBatch.id.in_(batch_ids),
                    ImportBatch.workspace_id == self._context.workspace_id,
                )
            )
        } if batch_ids else {}
        captures = {
            task.id: task
            for task in self._session.scalars(
                select(CaptureTask).where(
                    CaptureTask.id.in_(capture_ids),
                    CaptureTask.workspace_id == self._context.workspace_id,
                )
            )
        } if capture_ids else {}
        counts: dict[UUID, dict[str, int]] = {
            batch_id: {status.value: 0 for status in ImportRowStatus}
            for batch_id in batch_ids
        }
        if batch_ids:
            for batch_id, row_status, count in self._session.execute(
                select(
                    ImportRow.batch_id,
                    ImportRow.status,
                    func.count(),
                )
                .where(
                    ImportRow.workspace_id == self._context.workspace_id,
                    ImportRow.batch_id.in_(batch_ids),
                )
                .group_by(ImportRow.batch_id, ImportRow.status)
            ):
                counts[batch_id][row_status.value] = int(count)

        account_ids = {batch.account_id for batch in batches.values()}
        account_names = {
            account.id: account.name
            for account in self._session.scalars(
                select(PlatformAccount).where(
                    PlatformAccount.workspace_id
                    == self._context.workspace_id,
                    PlatformAccount.id.in_(account_ids),
                )
            )
        } if account_ids else {}
        operator_ids = {
            actor_id
            for actor_id in [
                *(batch.confirmed_by for batch in batches.values()),
                *(task.member_id for task in captures.values()),
            ]
            if actor_id is not None
        }
        operator_names = {
            member.id: member.display_name
            for member in self._session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id
                    == self._context.workspace_id,
                    WorkspaceMember.id.in_(operator_ids),
                )
            )
        } if operator_ids else {}

        items: list[dict[str, object]] = []
        empty_counts = {status.value: 0 for status in ImportRowStatus}
        for row in ordered:
            if row.item_kind == "capture":
                task = captures[row.item_id]
                if task.confirmed_at is not None:
                    status = "confirmed"
                    next_action = "open_result"
                elif task.status in {
                    CaptureTaskStatus.QUEUED,
                    CaptureTaskStatus.RUNNING,
                    CaptureTaskStatus.RETRYING,
                }:
                    status = "processing"
                    next_action = "wait"
                elif task.status == CaptureTaskStatus.FAILED:
                    status = "failed"
                    next_action = "retry"
                elif task.status == CaptureTaskStatus.CANCELLED:
                    status = "cancelled"
                    next_action = "none"
                else:
                    status = "waiting_confirmation"
                    next_action = "review"
                items.append(
                    {
                        "id": task.id,
                        "method": "extension",
                        "platform": task.platform.value,
                        "account_id": None,
                        "account_name": None,
                        "status": status,
                        "counts": empty_counts,
                        "created_at": task.collected_at,
                        "confirmed_at": task.confirmed_at,
                        "operator_name": operator_names.get(task.member_id),
                        "safe_error_code": (
                            "CAPTURE_TASK_FAILED"
                            if task.error_code
                            else None
                        ),
                        "next_action": next_action,
                    }
                )
                continue

            batch = batches[row.item_id]
            row_counts = counts[batch.id]
            if batch.status == ImportBatchStatus.CONFIRMED:
                status = "confirmed"
                next_action = "open_result"
            elif batch.recognition_status in {
                ScreenshotRecognitionStatus.PENDING,
                ScreenshotRecognitionStatus.PROCESSING,
            }:
                status = "processing"
                next_action = "wait"
            elif batch.recognition_status == ScreenshotRecognitionStatus.FAILED:
                status = "failed"
                next_action = "retry"
            else:
                status = "waiting_confirmation"
                next_action = "review"
            items.append(
                {
                    "id": batch.id,
                    "method": (
                        "tabular"
                        if batch.source_kind
                        in {ImportSourceKind.CSV, ImportSourceKind.XLSX}
                        else batch.source_kind.value
                    ),
                    "platform": batch.platform.value,
                    "account_id": batch.account_id,
                    "account_name": account_names.get(batch.account_id),
                    "status": status,
                    "counts": row_counts,
                    "created_at": batch.created_at,
                    "confirmed_at": batch.confirmed_at,
                    "operator_name": (
                        operator_names.get(batch.confirmed_by)
                        if batch.confirmed_by is not None
                        else None
                    ),
                    "safe_error_code": (
                        "RECOGNITION_FAILED"
                        if batch.recognition_status
                        == ScreenshotRecognitionStatus.FAILED
                        else (
                            "ROW_VALIDATION_FAILED"
                            if row_counts["failed"] > 0
                            else None
                        )
                    ),
                    "next_action": next_action,
                }
            )
        return items, total

    def _classify(
        self,
        batch: ImportBatch,
        normalized: dict[str, object],
        errors: list[dict[str, str]],
    ) -> tuple[ImportRowStatus, UUID | None, str | None]:
        if errors:
            return ImportRowStatus.FAILED, None, None
        return classify_duplicate(
            self._session,
            workspace_id=self._context.workspace_id,
            account_id=batch.account_id,
            platform=batch.platform,
            normalized_data=normalized,
        )

    @staticmethod
    def _exact_tokens(normalized: dict[str, object]) -> set[str]:
        tokens: set[str] = set()
        if normalized.get("platform_content_id"):
            tokens.add(f"id:{normalized['platform_content_id']}")
        if normalized.get("work_url"):
            tokens.add(f"url:{normalized['work_url']}")
        return tokens

    def _reject_batch_duplicate(
        self,
        normalized: dict[str, object],
        errors: list[dict[str, str]],
        seen_exact_tokens: set[str],
    ) -> None:
        if errors:
            return
        tokens = self._exact_tokens(normalized)
        if tokens & seen_exact_tokens:
            errors.append(
                {
                    "field": "dedupe",
                    "message": "duplicate exact key within import batch",
                }
            )
        else:
            seen_exact_tokens.update(tokens)

    def _add_rows(
        self,
        batch: ImportBatch,
        raw_rows: list[dict[str, object]],
        *,
        tabular: bool,
    ) -> None:
        seen_exact_tokens: set[str] = set()
        for row_number, raw_data in enumerate(raw_rows, start=2 if tabular else 1):
            if tabular:
                normalized, errors = normalize_tabular_row(
                    raw_data,
                    batch.header_mappings,
                    batch.platform,
                    batch.content_type,
                )
            else:
                normalized, errors = normalize_manual_row(
                    raw_data,
                    batch.platform,
                    batch.content_type,
                )
            self._reject_batch_duplicate(normalized, errors, seen_exact_tokens)
            status, matched_content_id, reason = self._classify(
                batch, normalized, errors
            )
            self._session.add(
                ImportRow(
                    workspace_id=self._context.workspace_id,
                    batch_id=batch.id,
                    row_number=row_number,
                    raw_data=raw_data,
                    normalized_data=normalized,
                    errors=errors,
                    status=status,
                    matched_content_id=matched_content_id,
                    dedupe_reason=reason,
                )
            )
        self._session.flush()

    def preview_file(
        self,
        *,
        account_id: UUID,
        platform: Platform,
        content_type: ContentType,
        file_name: str,
        data: bytes,
    ) -> ImportBatch:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._account(account_id, platform)
        parsed = read_tabular(file_name, data)
        source_kind = (
            ImportSourceKind.CSV
            if file_name.lower().endswith(".csv")
            else ImportSourceKind.XLSX
        )
        batch = ImportBatch(
            workspace_id=self._context.workspace_id,
            account_id=account_id,
            platform=platform,
            content_type=content_type,
            source_kind=source_kind,
            file_name=file_name,
            header_mappings=suggest_headers(parsed.headers, platform),
        )
        self._session.add(batch)
        self._session.flush()
        self._add_rows(batch, parsed.rows, tabular=True)
        return batch

    def preview_manual(
        self,
        *,
        account_id: UUID,
        platform: Platform,
        content_type: ContentType,
        rows: list[dict[str, object]],
    ) -> ImportBatch:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._account(account_id, platform)
        for row in rows:
            raw_column_id = row.get("column_campaign_id")
            if raw_column_id not in (None, ""):
                self._column_from_value(raw_column_id, account_id)
        batch = ImportBatch(
            workspace_id=self._context.workspace_id,
            account_id=account_id,
            platform=platform,
            content_type=content_type,
            source_kind=ImportSourceKind.MANUAL,
        )
        self._session.add(batch)
        self._session.flush()
        self._add_rows(batch, rows, tabular=False)
        return batch

    def preview_screenshot(
        self,
        *,
        account_id: UUID,
        platform: Platform,
        content_type: ContentType,
        file_name: str,
        mime_type: str,
        image: bytes,
        title: str,
        body: str,
        published_at: datetime,
        collected_at: datetime,
        retention_policy: str,
    ) -> ImportBatch:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        self._account(account_id, platform)
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("screenshot must be JPEG, PNG, or WebP")
        if not image or len(image) > 10 * 1024 * 1024:
            raise ValueError("screenshot must be between 1 byte and 10 MiB")
        if retention_policy not in {
            "delete_after_confirm",
            "retain_for_period",
            "retain_as_evidence",
            "workspace_policy",
        }:
            raise ValueError("invalid screenshot retention policy")
        settings = get_settings()
        binding = resolve_vision_binding(
            self._session,
            self._context,
            platform=platform,
            content_type=content_type,
            cipher=SecretCipher(
                settings.model_secret_encryption_key.get_secret_value()
            ),
            mock_mode=settings.app_mock_mode,
        )
        batch = ImportBatch(
            workspace_id=self._context.workspace_id,
            account_id=account_id,
            platform=platform,
            content_type=content_type,
            source_kind=ImportSourceKind.SCREENSHOT,
            recognition_status=ScreenshotRecognitionStatus.PENDING,
            file_name=file_name,
            screenshot_mime_type=mime_type,
            screenshot_sha256=hashlib.sha256(image).hexdigest(),
            screenshot_bytes=image,
            screenshot_metadata={
                "title": title,
                "body": body,
                "published_at": published_at.isoformat(),
                "collected_at": collected_at.isoformat(),
            },
            screenshot_retention_policy=retention_policy,
            recognition_model_config_id=binding.model_config_id,
            recognition_provider=binding.provider,
            recognition_model_id=binding.model_id,
            recognition_contract_version=binding.contract_version,
            recognition_config_version=binding.config_version,
            recognition_region=binding.region,
            recognition_metric_labels=binding.metric_labels,
        )
        self._session.add(batch)
        self._session.flush()
        return batch

    def update_mapping(
        self, batch_id: UUID, mapping: dict[str, str]
    ) -> ImportBatch:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        batch = self._batch(batch_id, for_update=True)
        if batch.status != ImportBatchStatus.PREVIEW:
            raise ValueError("confirmed import cannot be changed")
        by_header = {
            str(item["source_header"]): dict(item) for item in batch.header_mappings
        }
        for source_header, target_field in mapping.items():
            if source_header not in by_header:
                raise ValueError(f"unknown source header: {source_header}")
            by_header[source_header].update(
                {
                    "target_field": target_field,
                    "confidence": 1.0,
                    "high_confidence": True,
                }
            )
        batch.header_mappings = list(by_header.values())
        seen_exact_tokens: set[str] = set()
        for row in self.rows(batch.id):
            normalized, errors = normalize_tabular_row(
                row.raw_data,
                batch.header_mappings,
                batch.platform,
                batch.content_type,
            )
            self._reject_batch_duplicate(normalized, errors, seen_exact_tokens)
            status, matched_content_id, reason = self._classify(
                batch, normalized, errors
            )
            row.normalized_data = normalized
            row.errors = errors
            row.status = status
            row.matched_content_id = matched_content_id
            row.dedupe_reason = reason
        self._session.flush()
        return batch

    def update_row(
        self,
        batch_id: UUID,
        row_id: UUID,
        *,
        changes: dict[str, object],
        selected: bool | None,
    ) -> ImportBatch:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        batch = self._batch(batch_id, for_update=True)
        if batch.status != ImportBatchStatus.PREVIEW:
            raise ValueError("confirmed import cannot be changed")
        row = self._session.scalar(
            select(ImportRow).where(
                ImportRow.id == row_id,
                ImportRow.batch_id == batch.id,
                ImportRow.workspace_id == self._context.workspace_id,
            )
        )
        if row is None:
            raise LookupError("import row not found")
        merged = {**row.normalized_data, **changes}
        normalized, errors = normalize_manual_row(
            merged, batch.platform, batch.content_type
        )
        if batch.source_kind == ImportSourceKind.SCREENSHOT:
            previous_metrics = dict(
                cast(dict[str, object], row.normalized_data.get("metrics", {}))
            )
            previous_confidences = dict(
                cast(
                    dict[str, object],
                    row.normalized_data.get("metric_confidences", {}),
                )
            )
            changed_metrics = changes.get("metrics")
            submitted_metrics = (
                dict(changed_metrics) if isinstance(changed_metrics, dict) else {}
            )
            normalized["metric_confidences"] = {
                key: (
                    previous_confidences.get(key, 1.0)
                    if key in previous_metrics
                    and str(previous_metrics[key]) == str(submitted_metrics.get(key))
                    else 1.0
                )
                for key in dict(cast(dict[str, object], normalized["metrics"]))
            }
        other_tokens = set().union(
            *(
                self._exact_tokens(other.normalized_data)
                for other in self.rows(batch.id)
                if other.id != row.id and other.status != ImportRowStatus.FAILED
            )
        )
        self._reject_batch_duplicate(normalized, errors, other_tokens)
        status, matched_content_id, reason = self._classify(
            batch, normalized, errors
        )
        row.normalized_data = normalized
        row.errors = errors
        row.status = status
        row.matched_content_id = matched_content_id
        row.dedupe_reason = reason
        if selected is not None:
            row.selected = selected
        self._session.flush()
        return batch

    def _new_content(
        self, batch: ImportBatch, normalized: dict[str, object]
    ) -> Content:
        column_campaign_id = (
            self._column_from_value(
                normalized["column_campaign_id"],
                batch.account_id,
            ).id
            if normalized.get("column_campaign_id")
            else None
        )
        content = ContentService(self._session, self._context).create(
            account_id=batch.account_id,
            platform=batch.platform,
            content_type=batch.content_type,
            title=str(normalized["title"]),
            body=str(normalized["body"]),
            column_campaign_id=column_campaign_id,
            work_url=(str(normalized["work_url"]) if normalized.get("work_url") else None),
        )
        content.platform_content_id = (
            str(normalized["platform_content_id"])
            if normalized.get("platform_content_id")
            else None
        )
        content.status = ContentStatus.PUBLISHED
        content.published_title = content.title
        content.published_body = content.body
        content.published_at = datetime.fromisoformat(str(normalized["published_at"]))
        self._session.flush()
        return content

    def confirm(
        self, batch_id: UUID, selected_row_ids: list[UUID]
    ) -> dict[str, object]:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        batch = self._batch(batch_id, for_update=True)
        if batch.status == ImportBatchStatus.CONFIRMED:
            assert batch.confirmation_result is not None
            return batch.confirmation_result
        if (
            batch.source_kind == ImportSourceKind.SCREENSHOT
            and batch.recognition_status != ScreenshotRecognitionStatus.READY
        ):
            raise ValueError("screenshot recognition is not ready for confirmation")

        selected = set(selected_row_ids)
        content_ids: list[str] = []
        snapshot_ids: list[str] = []
        skipped_row_ids: list[str] = []
        snapshot_service = SnapshotService(self._session, self._context)
        for row in self.rows(batch.id):
            if row.id not in selected:
                continue
            row.selected = True
            if row.status == ImportRowStatus.FAILED:
                skipped_row_ids.append(str(row.id))
                continue
            if row.status == ImportRowStatus.UPDATE:
                content = self._session.scalar(
                    select(Content).where(
                        Content.id == row.matched_content_id,
                        Content.workspace_id == self._context.workspace_id,
                        Content.account_id == batch.account_id,
                        Content.platform == batch.platform,
                    )
                )
                if content is None:
                    raise LookupError("matched content not found")
            else:
                content = self._new_content(batch, row.normalized_data)

            confidences = dict(
                cast(
                    dict[str, object],
                    row.normalized_data.get("metric_confidences", {}),
                )
            )
            metrics = [
                SnapshotMetricInput(
                    key=key,
                    raw_value=Decimal(str(value)),
                    ocr_confidence=(
                        float(str(confidences[key]))
                        if batch.source_kind == ImportSourceKind.SCREENSHOT
                        and key in confidences
                        else None
                    ),
                )
                for key, value in dict(
                    cast(dict[str, object], row.normalized_data["metrics"])
                ).items()
            ]
            snapshot = snapshot_service.create(
                content.id,
                collected_at=datetime.fromisoformat(
                    str(row.normalized_data["collected_at"])
                ),
                source=(
                    SnapshotSource.MANUAL
                    if batch.source_kind == ImportSourceKind.MANUAL
                    else (
                        SnapshotSource.SCREENSHOT
                        if batch.source_kind == ImportSourceKind.SCREENSHOT
                        else SnapshotSource.TABULAR_IMPORT
                    )
                ),
                metrics=metrics,
                original_screenshot_asset_id=None,
            )
            snapshot_service.confirm(content.id, snapshot.id)
            content_ids.append(str(content.id))
            snapshot_ids.append(str(snapshot.id))

        result: dict[str, object] = {
            "batch_id": str(batch.id),
            "content_ids": content_ids,
            "snapshot_ids": snapshot_ids,
            "skipped_row_ids": skipped_row_ids,
        }
        batch.status = ImportBatchStatus.CONFIRMED
        batch.confirmed_at = datetime.now(UTC)
        batch.confirmed_by = self._context.member_id
        batch.confirmation_result = result
        if batch.source_kind == ImportSourceKind.SCREENSHOT:
            from app.modules.exports.deletion import RetentionService

            RetentionService(
                self._session,
                self._context,
            ).apply_screenshot_policy(
                batch,
                event="confirmed",
                evidence_reason=(
                    "confirmed import evidence"
                    if batch.screenshot_retention_policy
                    == "retain_as_evidence"
                    else None
                ),
            )
        self._session.flush()
        return result

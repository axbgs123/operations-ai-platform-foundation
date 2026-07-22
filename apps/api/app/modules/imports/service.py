from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.content.models import Content, ContentStatus
from app.modules.content.service import ContentService
from app.modules.imports.dedupe import classify_duplicate
from app.modules.imports.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportRow,
    ImportRowStatus,
    ImportSourceKind,
)
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
        content = ContentService(self._session, self._context).create(
            account_id=batch.account_id,
            platform=batch.platform,
            content_type=batch.content_type,
            title=str(normalized["title"]),
            body=str(normalized["body"]),
            column_campaign_id=None,
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

            metrics = [
                SnapshotMetricInput(key=key, raw_value=Decimal(str(value)))
                for key, value in dict(row.normalized_data["metrics"]).items()
            ]
            snapshot = snapshot_service.create(
                content.id,
                collected_at=datetime.fromisoformat(
                    str(row.normalized_data["collected_at"])
                ),
                source=(
                    SnapshotSource.MANUAL
                    if batch.source_kind == ImportSourceKind.MANUAL
                    else SnapshotSource.TABULAR_IMPORT
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
        self._session.flush()
        return result

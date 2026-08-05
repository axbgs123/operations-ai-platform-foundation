import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.core.storage import Storage
from app.modules.content.models import Content
from app.modules.exports.models import ExportKind, ExportStatus, ExportTask
from app.modules.exports.models import ManagedObjectState
from app.modules.exports.json_backup import render_lightweight_json
from app.modules.exports.report import (
    render_agent_execution_markdown,
    render_analysis_markdown,
)
from app.modules.exports.tabular import render_workspace_csv, safe_export_filename
from app.modules.exports.zip_backup import build_full_backup_zip
from app.modules.workspace.models import WorkspaceMember
from app.modules.workspace.permissions import Permission, PermissionDenied, require_permission


class ExportIdempotencyConflict(ValueError):
    pass


class ExportClaimLost(RuntimeError):
    pass


EXPORT_LEASE_DURATION = timedelta(minutes=5)
EXPORT_ENQUEUE_RECOVERY_DELAY = timedelta(minutes=5)


def export_fingerprint(kind: ExportKind, content_id: UUID | None) -> str:
    payload = json.dumps(
        {"kind": kind.value, "content_id": str(content_id) if content_id else None},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def create_export_task(
    session: Session,
    context: WorkspaceContext,
    *,
    kind: ExportKind,
    content_id: UUID | None,
    idempotency_key: str,
) -> tuple[ExportTask, bool]:
    if context.member_id is None:
        raise PermissionError("workspace member required")
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise ValueError("valid idempotency key is required")
    fingerprint = export_fingerprint(kind, content_id)
    existing = session.scalar(
        select(ExportTask).where(
            ExportTask.workspace_id == context.workspace_id,
            ExportTask.requested_by == context.member_id,
            ExportTask.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ExportIdempotencyConflict(
                "idempotency key already used for a different export"
            )
        return existing, False
    if kind is ExportKind.MARKDOWN:
        if content_id is None:
            raise ValueError("content_id is required for markdown export")
        content = session.scalar(
            select(Content.id).where(
                Content.id == content_id,
                Content.workspace_id == context.workspace_id,
                Content.deleted_at.is_(None),
            )
        )
        if content is None:
            raise LookupError("content not found")
    elif content_id is not None:
        raise ValueError("workspace backup export does not accept content_id")
    task = ExportTask(
        workspace_id=context.workspace_id,
        requested_by=context.member_id,
        kind=kind,
        content_id=content_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        status=ExportStatus.QUEUED,
    )
    try:
        with session.begin_nested():
            session.add(task)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(ExportTask).where(
                ExportTask.workspace_id == context.workspace_id,
                ExportTask.requested_by == context.member_id,
                ExportTask.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.request_fingerprint != fingerprint:
            raise ExportIdempotencyConflict(
                "idempotency key already used for a different export"
            )
        return existing, False
    return task, True


def process_export_task(
    session: Session,
    task_id: UUID,
    storage: Storage,
) -> None:
    now = datetime.now(UTC)
    claim_token = secrets.token_hex(16)
    claimed = cast(
        CursorResult,
        session.execute(
            update(ExportTask)
            .where(
                ExportTask.id == task_id,
                or_(
                    ExportTask.status == ExportStatus.QUEUED,
                    and_(
                        ExportTask.status == ExportStatus.RUNNING,
                        ExportTask.lease_expires_at.is_not(None),
                        ExportTask.lease_expires_at <= now,
                    ),
                ),
            )
            .values(
                status=ExportStatus.RUNNING,
                claim_token=claim_token,
                lease_expires_at=now + EXPORT_LEASE_DURATION,
            )
        ),
    )
    if claimed.rowcount != 1:
        session.rollback()
        return
    session.commit()
    task = session.get(ExportTask, task_id)
    if task is None:
        return
    workspace_id = task.workspace_id
    requested_by = task.requested_by
    kind = task.kind
    content_id = task.content_id
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == requested_by,
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.revoked_at.is_(None),
        )
    )
    try:
        if member is None:
            raise PermissionDenied("export member is unavailable")
        require_permission(member.role.value, Permission.WRITE_CONTENT)
    except PermissionDenied:
        _finalize_export_failure(
            session,
            task_id,
            claim_token,
            error_code="export_authorization_revoked",
        )
        return
    context = WorkspaceContext(
        workspace_id=workspace_id,
        member_id=requested_by,
        role=member.role.value,
    )

    def heartbeat() -> None:
        _renew_export_lease(session, task_id, claim_token)

    try:
        heartbeat()
        if kind is ExportKind.CSV:
            content = render_workspace_csv(
                session,
                context,
                heartbeat=heartbeat,
            )
            file_name = safe_export_filename(
                f"workspace-{workspace_id}-data", "csv"
            )
            mime_type = "text/csv"
        elif kind is ExportKind.MARKDOWN:
            if content_id is None:
                raise ValueError("markdown export is missing content")
            raw_agent_run_id = (
                task.idempotency_key.removeprefix("agent-export:")
                if task.idempotency_key.startswith("agent-export:")
                else None
            )
            markdown = (
                render_agent_execution_markdown(
                    session,
                    context,
                    content_id,
                    UUID(raw_agent_run_id),
                )
                if raw_agent_run_id is not None
                else render_analysis_markdown(
                    session,
                    context,
                    content_id,
                )
            )
            content = markdown.encode("utf-8")
            file_name = safe_export_filename(
                (
                    f"content-{content_id}-agent-execution"
                    if raw_agent_run_id is not None
                    else f"content-{content_id}-analysis"
                ),
                "md",
            )
            mime_type = "text/markdown"
        elif kind is ExportKind.JSON:
            content = render_lightweight_json(session, context)
            file_name = safe_export_filename(
                f"workspace-{workspace_id}-backup", "json"
            )
            mime_type = "application/json"
        else:
            content = build_full_backup_zip(session, context, storage)
            file_name = safe_export_filename(
                f"workspace-{workspace_id}-full-backup", "zip"
            )
            mime_type = "application/zip"
        heartbeat()
        object_key = (
            f"workspaces/{workspace_id}/exports/{task_id}/"
            f"{claim_token}/{file_name}"
        )
        from app.modules.exports.deletion import RetentionService

        managed_object = RetentionService(
            session,
            context,
        ).register_managed_object(
            owner_type="export_job",
            owner_id=task_id,
            object_key=object_key,
            managed_prefix=f"workspaces/{workspace_id}/exports/{task_id}/",
            purge_at=datetime.now(UTC) + timedelta(minutes=15),
            claim_token=claim_token,
            lease_expires_at=task.lease_expires_at,
        )
        session.commit()
        storage.put_object(object_key, content, mime_type=mime_type)
    except Exception:
        _finalize_export_failure(
            session,
            task_id,
            claim_token,
            error_code="export_failed",
        )
        return
    finalized = _finalize_export_success(
        session,
        task_id,
        claim_token,
        object_key=object_key,
        file_name=file_name,
        mime_type=mime_type,
    )
    if finalized:
        managed = session.get(type(managed_object), managed_object.id)
        if managed is not None:
            managed.state = ManagedObjectState.REFERENCED
            managed.claim_token = None
            managed.lease_expires_at = None
            managed.purge_at = None
            session.commit()


def _renew_export_lease(
    session: Session,
    task_id: UUID,
    claim_token: str,
) -> None:
    renewed = cast(
        CursorResult,
        session.execute(
            update(ExportTask)
            .where(
                ExportTask.id == task_id,
                ExportTask.status == ExportStatus.RUNNING,
                ExportTask.claim_token == claim_token,
            )
            .values(
                lease_expires_at=datetime.now(UTC) + EXPORT_LEASE_DURATION
            )
        ),
    )
    if renewed.rowcount != 1:
        session.rollback()
        raise ExportClaimLost("export worker claim is no longer current")
    session.commit()


def _finalize_export_failure(
    session: Session,
    task_id: UUID,
    claim_token: str,
    *,
    error_code: str,
) -> bool:
    result = cast(
        CursorResult,
        session.execute(
            update(ExportTask)
            .where(
                ExportTask.id == task_id,
                ExportTask.status == ExportStatus.RUNNING,
                ExportTask.claim_token == claim_token,
            )
            .values(
                status=ExportStatus.FAILED,
                object_key=None,
                file_name=None,
                mime_type=None,
                error_code=error_code,
                claim_token=None,
                lease_expires_at=None,
                completed_at=datetime.now(UTC),
            )
        ),
    )
    session.commit()
    return result.rowcount == 1


def _finalize_export_success(
    session: Session,
    task_id: UUID,
    claim_token: str,
    *,
    object_key: str,
    file_name: str,
    mime_type: str,
) -> bool:
    result = cast(
        CursorResult,
        session.execute(
            update(ExportTask)
            .where(
                ExportTask.id == task_id,
                ExportTask.status == ExportStatus.RUNNING,
                ExportTask.claim_token == claim_token,
            )
            .values(
                object_key=object_key,
                file_name=file_name,
                mime_type=mime_type,
                error_code=None,
                status=ExportStatus.SUCCEEDED,
                claim_token=None,
                lease_expires_at=None,
                completed_at=datetime.now(UTC),
            )
        ),
    )
    session.commit()
    return result.rowcount == 1


def mark_export_enqueued(
    session: Session,
    task_id: UUID,
    *,
    now: datetime | None = None,
) -> bool:
    result = cast(
        CursorResult,
        session.execute(
            update(ExportTask)
            .where(
                ExportTask.id == task_id,
                ExportTask.status == ExportStatus.QUEUED,
            )
            .values(enqueued_at=now or datetime.now(UTC))
        ),
    )
    return result.rowcount == 1


def recoverable_export_task_ids(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[UUID]:
    current = now or datetime.now(UTC)
    return list(
        session.scalars(
            select(ExportTask.id)
            .where(
                or_(
                    and_(
                        ExportTask.status == ExportStatus.QUEUED,
                        or_(
                            ExportTask.enqueued_at.is_(None),
                            ExportTask.enqueued_at
                            <= current - EXPORT_ENQUEUE_RECOVERY_DELAY,
                        ),
                    ),
                    and_(
                        ExportTask.status == ExportStatus.RUNNING,
                        ExportTask.lease_expires_at.is_not(None),
                        ExportTask.lease_expires_at <= current,
                    ),
                )
            )
            .order_by(ExportTask.created_at, ExportTask.id)
            .limit(limit)
        )
    )

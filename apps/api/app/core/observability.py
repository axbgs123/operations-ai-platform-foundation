from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from random import random
from typing import Any, Callable, Literal, Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    func,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base, UTCDateTime, UUIDPrimaryKeyMixin
from app.core.security import WorkspaceContext


HIGH_CARDINALITY_LABELS = frozenset(
    {
        "workspace_id",
        "member_id",
        "content_id",
        "request_id",
        "task_id",
        "title",
        "copy",
        "url",
        "error_message",
    }
)
TECHNICAL_METRIC_LABELS: dict[str, frozenset[str]] = {
    "http_requests_total": frozenset({"method", "route", "status_class"}),
    "http_request_duration_ms": frozenset({"method", "route"}),
    "rate_limit_rejections_total": frozenset({"category"}),
    "tasks_total": frozenset({"task_type", "status"}),
    "task_retries_total": frozenset({"task_type"}),
    "task_queue_duration_ms": frozenset({"task_type"}),
    "task_execution_duration_ms": frozenset({"task_type"}),
    "task_dead_letter_total": frozenset({"task_type"}),
    "readiness": frozenset({"component", "status"}),
}
TERMINAL_ERRORS = frozenset(
    {
        "PERMISSION_DENIED",
        "VALIDATION_FAILED",
        "REFERENCE_CONFLICT",
        "SAFETY_REJECTED",
        "IDEMPOTENCY_CONFLICT",
    }
)
TRANSIENT_ERRORS = frozenset(
    {
        "NETWORK_TIMEOUT",
        "STORAGE_TIMEOUT",
        "STORAGE_TEMPORARY_FAILURE",
        "REDIS_UNAVAILABLE",
        "DEPENDENCY_NOT_READY",
    }
)


class OperationalTask(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: UUID
    task_type: str
    workspace_id: UUID
    status: str
    progress: int | None = Field(default=None, ge=0, le=100)
    phase: str | None
    created_at: datetime
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    retry_count: int = Field(ge=0)
    max_retries: int = Field(ge=0)
    next_retry_at: datetime | None
    cancelable: bool
    retryable: bool
    error_code: str | None
    status_detail: str | None = Field(default=None, max_length=240)
    request_id: str | None
    fencing_token: int = Field(default=0, ge=0)


class TechnicalMetrics:
    """Small OpenTelemetry-compatible boundary with fixed low-cardinality labels."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], float] = (
            defaultdict(float)
        )

    def record(
        self,
        name: str,
        value: float = 1,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        if name not in TECHNICAL_METRIC_LABELS:
            raise ValueError("technical metric is not registered")
        safe_labels = labels or {}
        if set(safe_labels) - TECHNICAL_METRIC_LABELS[name]:
            raise ValueError("metric label is not allowed")
        if set(safe_labels) & HIGH_CARDINALITY_LABELS:
            raise ValueError("high-cardinality metric label is forbidden")
        key = (name, tuple(sorted(safe_labels.items())))
        with self._lock:
            self._values[key] += value

    def snapshot(self) -> dict[tuple[str, tuple[tuple[str, str], ...]], float]:
        with self._lock:
            return dict(self._values)


technical_metrics = TechnicalMetrics()


class DeadLetterDiagnostic(BaseModel):
    error_code: str | None
    failure_stage: str | None
    retry_count: int
    last_attempt_at: datetime
    next_action: str
    request_id: str | None
    task_id: UUID
    summary: str
    status: Literal["dead_letter"]


@dataclass(frozen=True)
class OperationEvent:
    task_id: UUID
    task_type: str
    workspace_id: UUID
    action: str
    idempotency_key: str
    created_at: datetime
    result_task_id: UUID | None = None


class TaskOperationEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "task_operation_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "task_id",
            "action",
            "idempotency_key",
            name="uq_task_operation_events_idempotency",
        ),
        Index(
            "ix_task_operation_events_workspace_task_time",
            "workspace_id",
            "task_type",
            "created_at",
        ),
        Index(
            "ix_task_operation_events_task",
            "task_id",
            "created_at",
        ),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    task_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    task_type: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    request_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspace_members.id", ondelete="SET NULL"),
    )
    error_code: Mapped[str | None] = mapped_column(String(80))
    failure_stage: Mapped[str | None] = mapped_column(String(80))
    result_task_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class OperationsStore(Protocol):
    def get(self, task_type: str, task_id: UUID) -> OperationalTask | None: ...
    def get_for_update(
        self,
        task_type: str,
        task_id: UUID,
    ) -> OperationalTask | None: ...
    def save(self, task: OperationalTask) -> OperationalTask: ...
    def retry_task(
        self,
        task: OperationalTask,
        *,
        idempotency_key: str,
    ) -> OperationalTask: ...
    def event(
        self,
        task: OperationalTask,
        action: str,
        idempotency_key: str,
        result_task_id: UUID | None = None,
    ) -> OperationEvent: ...
    def find_event(
        self,
        task_id: UUID,
        action: str,
        idempotency_key: str,
    ) -> OperationEvent | None: ...
    def list(
        self,
        workspace_id: UUID,
        *,
        task_type: str | None = None,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[OperationalTask]: ...


class InMemoryOperationsStore:
    def __init__(self, tasks: list[OperationalTask] | None = None) -> None:
        self.tasks = {task.task_id: task for task in tasks or []}
        self.events: list[OperationEvent] = []

    def get(self, task_type: str, task_id: UUID) -> OperationalTask | None:
        task = self.tasks.get(task_id)
        return task if task is not None and task.task_type == task_type else None

    def get_for_update(
        self,
        task_type: str,
        task_id: UUID,
    ) -> OperationalTask | None:
        return self.get(task_type, task_id)

    def save(self, task: OperationalTask) -> OperationalTask:
        self.tasks[task.task_id] = task
        return task

    def event(
        self,
        task: OperationalTask,
        action: str,
        idempotency_key: str,
        result_task_id: UUID | None = None,
    ) -> OperationEvent:
        existing = self.find_event(task.task_id, action, idempotency_key)
        if existing is not None:
            return existing
        event = OperationEvent(
            task_id=task.task_id,
            task_type=task.task_type,
            workspace_id=task.workspace_id,
            action=action,
            idempotency_key=idempotency_key,
            created_at=datetime.now(UTC),
            result_task_id=result_task_id,
        )
        self.events.append(event)
        return event

    def retry_task(
        self,
        task: OperationalTask,
        *,
        idempotency_key: str,
    ) -> OperationalTask:
        retried = task.model_copy(
            update={
                "status": "retrying",
                "retry_count": task.retry_count + 1,
                "next_retry_at": datetime.now(UTC)
                + calculate_retry_delay(task.retry_count + 1),
                "updated_at": datetime.now(UTC),
                "fencing_token": task.fencing_token + 1,
            }
        )
        return self.save(retried)

    def find_event(
        self,
        task_id: UUID,
        action: str,
        idempotency_key: str,
    ) -> OperationEvent | None:
        return next(
            (
                event
                for event in self.events
                if event.task_id == task_id
                and event.action == action
                and event.idempotency_key == idempotency_key
            ),
            None,
        )

    def can_publish(self, task_id: UUID, *, fencing_token: int) -> bool:
        task = self.tasks[task_id]
        return task.status not in {"cancelled", "compensation_required"} and (
            task.fencing_token == fencing_token
        )

    def list(
        self,
        workspace_id: UUID,
        *,
        task_type: str | None = None,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[OperationalTask]:
        records = [
            task
            for task in self.tasks.values()
            if task.workspace_id == workspace_id
            and (task_type is None or task.task_type == task_type)
            and (status is None or task.status == status)
            and (created_after is None or task.created_at >= created_after)
            and (created_before is None or task.created_at <= created_before)
        ]
        return sorted(
            records, key=lambda item: (item.created_at, item.task_id), reverse=True
        )


@dataclass(frozen=True)
class _TaskAdapter:
    task_type: str
    model: type[Any]
    status_enum: type | None = None
    status_attr: str = "status"
    status_map: tuple[tuple[str, str], ...] = ()
    created_attr: str = "created_at"
    updated_attr: str = "updated_at"
    phase_attr: str | None = None
    retry_attr: str | None = None
    completed_attr: str | None = "completed_at"
    error_attr: str | None = "error_code"
    cancelable_statuses: frozenset[str] = frozenset()
    retryable_statuses: frozenset[str] = frozenset({"failed"})
    max_retries: int = 3
    include_statuses: frozenset[str] | None = None


def _task_adapters() -> tuple[_TaskAdapter, ...]:
    from app.modules.analysis.models import AnalysisRun, ProductEventOutbox
    from app.modules.exports.models import (
        ExportTask,
        FullRestoreStatus,
        KnowledgeIndexRebuild,
        ManagedObject,
        RestoreJob,
        WorkspaceDeletionJob,
        WorkspaceDeletionStatus,
    )
    from app.modules.generation.models import TextGenerationRun, TextGenerationRunStatus
    from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
    from app.modules.imports.models import ImportBatch
    from app.modules.risk_rag.models import RiskScan, RiskScanStatus

    return (
        _TaskAdapter(
            "analysis",
            AnalysisRun,
            retry_attr="attempt_count",
            cancelable_statuses=frozenset(),
        ),
        _TaskAdapter(
            "generation",
            TextGenerationRun,
            TextGenerationRunStatus,
            cancelable_statuses=frozenset({"queued", "running"}),
        ),
        _TaskAdapter("export", ExportTask, cancelable_statuses=frozenset()),
        _TaskAdapter(
            "restore",
            RestoreJob,
            FullRestoreStatus,
            phase_attr="phase",
            cancelable_statuses=frozenset({"queued", "running", "retrying"}),
        ),
        _TaskAdapter(
            "extension_capture",
            CaptureTask,
            CaptureTaskStatus,
            created_attr="collected_at",
            updated_attr="collected_at",
            completed_attr="confirmed_at",
            cancelable_statuses=frozenset({"queued", "running", "retrying"}),
            retryable_statuses=frozenset(),
        ),
        _TaskAdapter(
            "import_recognition",
            ImportBatch,
            status_attr="recognition_status",
            status_map=(
                ("pending", "queued"),
                ("processing", "running"),
                ("ready", "succeeded"),
            ),
            completed_attr="confirmed_at",
            cancelable_statuses=frozenset(),
            retryable_statuses=frozenset(),
            include_statuses=frozenset({"queued", "running", "succeeded", "failed"}),
        ),
        _TaskAdapter(
            "risk_scan",
            RiskScan,
            RiskScanStatus,
            cancelable_statuses=frozenset(),
            retryable_statuses=frozenset(),
        ),
        _TaskAdapter(
            "workspace_deletion",
            WorkspaceDeletionJob,
            WorkspaceDeletionStatus,
            phase_attr="phase",
            cancelable_statuses=frozenset({"queued", "retrying"}),
        ),
        _TaskAdapter(
            "knowledge_index",
            KnowledgeIndexRebuild,
            completed_attr=None,
            cancelable_statuses=frozenset(),
            retryable_statuses=frozenset(),
        ),
        _TaskAdapter(
            "retention",
            ManagedObject,
            status_attr="state",
            retry_attr="attempt_count",
            completed_attr=None,
            cancelable_statuses=frozenset({"scheduled", "retrying"}),
            retryable_statuses=frozenset(),
        ),
        _TaskAdapter(
            "product_event_outbox",
            ProductEventOutbox,
            retry_attr="attempt_count",
            completed_attr="processed_at",
            cancelable_statuses=frozenset(),
        ),
    )


def _status_value(value: object) -> str:
    return str(getattr(value, "value", value))


class SQLAlchemyOperationsStore:
    def __init__(
        self, session: Session, *, request_id: str, actor_id: UUID | None
    ) -> None:
        self._session = session
        self._request_id = request_id
        self._actor_id = actor_id

    @staticmethod
    def _adapter(task_type: str) -> _TaskAdapter | None:
        return next(
            (item for item in _task_adapters() if item.task_type == task_type),
            None,
        )

    def _to_task(self, adapter: _TaskAdapter, instance: object) -> OperationalTask:
        status = (
            (
                "succeeded"
                if getattr(instance, "processed_at", None) is not None
                else "failed"
                if getattr(instance, "error_code", None)
                else "queued"
            )
            if adapter.task_type == "product_event_outbox"
            else _status_value(getattr(instance, adapter.status_attr))
        )
        status = dict(adapter.status_map).get(status, status)
        created_at = cast(datetime, getattr(instance, adapter.created_attr))
        updated_at = cast(datetime, getattr(instance, adapter.updated_attr, created_at))
        completed_at = (
            cast(datetime | None, getattr(instance, adapter.completed_attr, None))
            if adapter.completed_attr
            else None
        )
        retry_count = (
            int(getattr(instance, adapter.retry_attr, 0))
            if adapter.retry_attr
            else int(
                self._session.scalar(
                    select(func.count(TaskOperationEvent.id)).where(
                        TaskOperationEvent.task_id == getattr(instance, "id"),
                        TaskOperationEvent.workspace_id
                        == getattr(instance, "workspace_id"),
                        TaskOperationEvent.action == "manual_retry",
                    )
                )
                or 0
            )
        )
        if status == "failed" and retry_count >= adapter.max_retries:
            status = "dead_letter"
        phase = (
            _status_value(getattr(instance, adapter.phase_attr))
            if adapter.phase_attr
            else status
        )
        request_id = self._session.scalar(
            select(TaskOperationEvent.request_id)
            .where(
                TaskOperationEvent.task_id == getattr(instance, "id"),
                TaskOperationEvent.workspace_id == getattr(instance, "workspace_id"),
            )
            .order_by(TaskOperationEvent.created_at.desc())
            .limit(1)
        )
        event_fencing = (
            self._session.scalar(
                select(TaskOperationEvent.id).where(
                    TaskOperationEvent.task_id == getattr(instance, "id"),
                    TaskOperationEvent.action.in_(("cancelled", "manual_retry")),
                )
            )
            is not None
        )
        fencing_token = int(getattr(instance, "operation_version", int(event_fencing)))
        return OperationalTask(
            task_id=getattr(instance, "id"),
            task_type=adapter.task_type,
            workspace_id=getattr(instance, "workspace_id"),
            status=status,
            progress=100
            if status == "succeeded"
            else 0
            if status == "queued"
            else None,
            phase=phase,
            created_at=created_at,
            started_at=created_at if status != "queued" else None,
            updated_at=updated_at,
            completed_at=completed_at,
            retry_count=retry_count,
            max_retries=adapter.max_retries,
            next_retry_at=getattr(instance, "next_attempt_at", None),
            cancelable=status in adapter.cancelable_statuses,
            retryable=(
                (status in adapter.retryable_statuses or status == "dead_letter")
                and RetryClass.classify(getattr(instance, "error_code", None))
                == "transient"
            ),
            error_code=(
                getattr(instance, adapter.error_attr, None)
                if adapter.error_attr
                else None
            ),
            status_detail=(
                "需要人工补偿"
                if phase == "compensation_required"
                else "任务状态可通过安全诊断查看"
            ),
            request_id=request_id,
            fencing_token=fencing_token,
        )

    def get(self, task_type: str, task_id: UUID) -> OperationalTask | None:
        adapter = self._adapter(task_type)
        if adapter is None:
            return None
        instance = self._session.get(adapter.model, task_id)
        return self._to_task(adapter, instance) if instance is not None else None

    def get_for_update(
        self,
        task_type: str,
        task_id: UUID,
    ) -> OperationalTask | None:
        adapter = self._adapter(task_type)
        if adapter is None:
            return None
        instance = self._session.scalar(
            select(adapter.model)
            .where(getattr(adapter.model, "id") == task_id)
            .with_for_update()
        )
        return self._to_task(adapter, instance) if instance is not None else None

    def save(self, task: OperationalTask) -> OperationalTask:
        adapter = self._adapter(task.task_type)
        if adapter is None:
            raise LookupError("task adapter not found")
        instance = self._session.get(adapter.model, task.task_id)
        if instance is None:
            raise LookupError("task not found")
        if adapter.task_type == "product_event_outbox":
            setattr(instance, "error_code", None)
        else:
            status: object = task.status
            if adapter.status_enum is not None:
                status = adapter.status_enum(task.status)
            inverse_status_map = {
                target: source for source, target in adapter.status_map
            }
            persisted_status = inverse_status_map.get(cast(str, status), status)
            setattr(instance, adapter.status_attr, persisted_status)
        if hasattr(instance, "completed_at"):
            setattr(instance, "completed_at", task.completed_at)
        if adapter.retry_attr:
            setattr(instance, adapter.retry_attr, task.retry_count)
        if hasattr(instance, "next_attempt_at"):
            setattr(instance, "next_attempt_at", task.next_retry_at)
        if task.status in {"cancelled", "retrying"}:
            if hasattr(instance, "claim_token"):
                setattr(instance, "claim_token", None)
            if hasattr(instance, "lease_expires_at"):
                setattr(instance, "lease_expires_at", None)
        self._session.flush()
        return self._to_task(adapter, instance)

    def event(
        self,
        task: OperationalTask,
        action: str,
        idempotency_key: str,
        result_task_id: UUID | None = None,
    ) -> OperationEvent:
        existing = self.find_event(task.task_id, action, idempotency_key)
        if existing is not None:
            return existing
        created_at = datetime.now(UTC)
        self._session.add(
            TaskOperationEvent(
                workspace_id=task.workspace_id,
                task_id=task.task_id,
                task_type=task.task_type,
                action=action,
                idempotency_key=idempotency_key,
                request_id=self._request_id,
                actor_id=self._actor_id,
                error_code=task.error_code,
                failure_stage=task.phase,
                result_task_id=result_task_id,
                created_at=created_at,
            )
        )
        self._session.flush()
        return OperationEvent(
            task_id=task.task_id,
            task_type=task.task_type,
            workspace_id=task.workspace_id,
            action=action,
            idempotency_key=idempotency_key,
            created_at=created_at,
            result_task_id=result_task_id,
        )

    def find_event(
        self,
        task_id: UUID,
        action: str,
        idempotency_key: str,
    ) -> OperationEvent | None:
        record = self._session.scalar(
            select(TaskOperationEvent).where(
                TaskOperationEvent.task_id == task_id,
                TaskOperationEvent.action == action,
                TaskOperationEvent.idempotency_key == idempotency_key,
            )
        )
        if record is None:
            return None
        return OperationEvent(
            task_id=record.task_id,
            task_type=record.task_type,
            workspace_id=record.workspace_id,
            action=record.action,
            idempotency_key=record.idempotency_key,
            created_at=record.created_at,
            result_task_id=record.result_task_id,
        )

    def retry_task(
        self,
        task: OperationalTask,
        *,
        idempotency_key: str,
    ) -> OperationalTask:
        adapter = self._adapter(task.task_type)
        if adapter is None:
            raise ValueError("TASK_NOT_RETRYABLE")
        instance = self._session.get(adapter.model, task.task_id)
        if instance is None:
            raise LookupError("task not found")
        if task.task_type == "generation":
            from app.modules.generation.text_service import retry_text_generation

            return self._to_task(
                adapter,
                retry_text_generation(self._session, task.task_id),
            )
        if task.task_type == "analysis":
            from app.modules.analysis.models import AnalysisRun, AnalysisRunStatus

            analysis_original = cast(AnalysisRun, instance)
            analysis_clone = AnalysisRun(
                workspace_id=analysis_original.workspace_id,
                account_id=analysis_original.account_id,
                content_id=analysis_original.content_id,
                benchmark_run_id=analysis_original.benchmark_run_id,
                snapshot_ids=list(analysis_original.snapshot_ids),
                status=AnalysisRunStatus.PENDING,
                trigger_kind=analysis_original.trigger_kind,
                cache_key=analysis_original.cache_key,
                evidence_bundle=dict(analysis_original.evidence_bundle),
                model_version=analysis_original.model_version,
                prompt_version=analysis_original.prompt_version,
                algorithm_version=analysis_original.algorithm_version,
                benchmark_algorithm_version=(
                    analysis_original.benchmark_algorithm_version
                ),
                attempt_count=0,
                next_attempt_at=datetime.now(UTC),
                lease_expires_at=None,
                report=None,
                error_code=None,
                error_message=None,
                requested_by=analysis_original.requested_by,
                completed_at=None,
            )
            self._session.add(analysis_clone)
            self._session.flush()
            return self._to_task(adapter, analysis_clone)
        if task.task_type == "export":
            from app.modules.exports.models import ExportStatus, ExportTask

            export_original = cast(ExportTask, instance)
            export_clone = ExportTask(
                workspace_id=export_original.workspace_id,
                requested_by=cast(UUID, export_original.requested_by),
                kind=export_original.kind,
                idempotency_key=f"ops-retry:{idempotency_key}",
                request_fingerprint=export_original.request_fingerprint,
                status=ExportStatus.QUEUED,
                content_id=export_original.content_id,
                object_key=None,
                file_name=None,
                mime_type=None,
                error_code=None,
                enqueued_at=None,
                claim_token=None,
                lease_expires_at=None,
                completed_at=None,
            )
            self._session.add(export_clone)
            self._session.flush()
            return self._to_task(adapter, export_clone)
        if task.task_type in {
            "restore",
            "workspace_deletion",
            "product_event_outbox",
        }:
            retried = task.model_copy(
                update={
                    "status": "retrying",
                    "retry_count": task.retry_count + 1,
                    "next_retry_at": datetime.now(UTC),
                    "updated_at": datetime.now(UTC),
                    "error_code": None,
                    "fencing_token": task.fencing_token + 1,
                }
            )
            return self.save(retried)
        raise ValueError("TASK_NOT_RETRYABLE")

    def list(
        self,
        workspace_id: UUID,
        *,
        task_type: str | None = None,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[OperationalTask]:
        adapters = [
            adapter
            for adapter in _task_adapters()
            if task_type is None or adapter.task_type == task_type
        ]
        tasks: list[OperationalTask] = []
        for adapter in adapters:
            model_workspace_id = getattr(adapter.model, "workspace_id")
            statement: Any = select(adapter.model).where(
                model_workspace_id == workspace_id
            )
            for instance in self._session.scalars(statement):
                task = self._to_task(adapter, instance)
                if (
                    adapter.include_statuses is not None
                    and task.status not in adapter.include_statuses
                ):
                    continue
                if status is not None and task.status != status:
                    continue
                if created_after is not None and task.created_at < created_after:
                    continue
                if created_before is not None and task.created_at > created_before:
                    continue
                tasks.append(task)
        return sorted(
            tasks,
            key=lambda item: (item.created_at, item.task_id),
            reverse=True,
        )


def record_task_correlation(
    session: Session,
    *,
    workspace_id: UUID,
    task_id: UUID,
    task_type: str,
    request_id: str,
    action: str = "worker_started",
) -> None:
    existing = session.scalar(
        select(TaskOperationEvent.id).where(
            TaskOperationEvent.workspace_id == workspace_id,
            TaskOperationEvent.task_id == task_id,
            TaskOperationEvent.action == action,
            TaskOperationEvent.idempotency_key == request_id,
        )
    )
    if existing is not None:
        return
    session.add(
        TaskOperationEvent(
            workspace_id=workspace_id,
            task_id=task_id,
            task_type=task_type,
            action=action,
            idempotency_key=request_id,
            request_id=request_id,
            actor_id=None,
            error_code=None,
            failure_stage=None,
            result_task_id=None,
            created_at=datetime.now(UTC),
        )
    )


class RetryClass:
    @staticmethod
    def classify(error_code: str | None) -> Literal["transient", "terminal"]:
        normalized = (error_code or "").upper()
        return (
            "transient"
            if normalized in TRANSIENT_ERRORS
            or normalized.endswith(("_TIMEOUT", "_TEMPORARY_FAILURE"))
            else "terminal"
        )


def calculate_retry_delay(
    attempt: int,
    *,
    jitter: Callable[[], float] = random,
) -> timedelta:
    bounded_attempt = max(1, attempt)
    base_seconds = min(15 * 60, 15 * (2 ** (bounded_attempt - 1)))
    return timedelta(seconds=min(15 * 60, base_seconds + base_seconds * 0.2 * jitter()))


class OperationsService:
    def __init__(self, store: OperationsStore) -> None:
        self._store = store

    @staticmethod
    def _admin(context: WorkspaceContext) -> None:
        if context.role != "admin":
            raise PermissionError("admin role required")

    def _task(
        self,
        context: WorkspaceContext,
        task_type: str,
        task_id: UUID,
        *,
        for_update: bool = False,
    ) -> OperationalTask:
        task = (
            self._store.get_for_update(task_type, task_id)
            if for_update
            else self._store.get(task_type, task_id)
        )
        if task is None or task.workspace_id != context.workspace_id:
            raise LookupError("task not found")
        return task

    def list_tasks(
        self,
        context: WorkspaceContext,
        *,
        task_type: str | None = None,
        status: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> list[OperationalTask]:
        if context.role not in {"admin", "editor"}:
            raise PermissionError("operations access denied")
        return self._store.list(
            context.workspace_id,
            task_type=task_type,
            status=status,
            created_after=created_after,
            created_before=created_before,
        )

    def read_task(
        self,
        context: WorkspaceContext,
        task_type: str,
        task_id: UUID,
    ) -> OperationalTask:
        if context.role not in {"admin", "editor"}:
            raise PermissionError("operations access denied")
        return self._task(context, task_type, task_id)

    def cancel(
        self,
        context: WorkspaceContext,
        *,
        task_type: str,
        task_id: UUID,
        idempotency_key: str,
    ) -> OperationalTask:
        self._admin(context)
        task = self._task(context, task_type, task_id, for_update=True)
        if (
            task.status == "compensation_required"
            or task.phase == "compensation_required"
        ):
            raise ValueError("TASK_COMPENSATION_REQUIRED")
        if task.status in {"succeeded", "failed", "cancelled", "dead_letter"}:
            return task
        if not task.cancelable:
            raise ValueError("TASK_NOT_CANCELABLE")
        if self._store.find_event(task_id, "cancelled", idempotency_key):
            return task
        cancelled = task.model_copy(
            update={
                "status": "cancelled",
                "cancelable": False,
                "retryable": False,
                "completed_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
                "fencing_token": task.fencing_token + 1,
            }
        )
        self._store.save(cancelled)
        self._store.event(cancelled, "cancelled", idempotency_key)
        technical_metrics.record(
            "tasks_total",
            labels={"task_type": task.task_type, "status": "cancelled"},
        )
        return cancelled

    def retry(
        self,
        context: WorkspaceContext,
        *,
        task_type: str,
        task_id: UUID,
        idempotency_key: str,
    ) -> OperationalTask:
        self._admin(context)
        task = self._task(context, task_type, task_id, for_update=True)
        existing = self._store.find_event(task_id, "manual_retry", idempotency_key)
        if existing:
            result_id = existing.result_task_id or existing.task_id
            return self._store.get(task_type, result_id) or task
        if not task.retryable or RetryClass.classify(task.error_code) == "terminal":
            raise ValueError("TASK_NOT_RETRYABLE")
        retried = self._store.retry_task(
            task,
            idempotency_key=idempotency_key,
        )
        self._store.event(
            task,
            "manual_retry",
            idempotency_key,
            result_task_id=retried.task_id,
        )
        technical_metrics.record(
            "task_retries_total",
            labels={"task_type": task.task_type},
        )
        return self._store.get(task_type, retried.task_id) or retried

    def safe_diagnostic(
        self,
        context: WorkspaceContext,
        task_type: str,
        task_id: UUID,
    ) -> DeadLetterDiagnostic:
        self._admin(context)
        task = self._task(context, task_type, task_id)
        if task.status != "dead_letter":
            raise ValueError("TASK_NOT_DEAD_LETTER")
        technical_metrics.record(
            "task_dead_letter_total",
            labels={"task_type": task.task_type},
        )
        return DeadLetterDiagnostic(
            error_code=task.error_code,
            failure_stage=task.phase,
            retry_count=task.retry_count,
            last_attempt_at=task.updated_at,
            next_action="检查依赖后发起受控重试",
            request_id=task.request_id,
            task_id=task.task_id,
            summary="任务已达到重试上限；诊断不包含原始异常或任务载荷。",
            status="dead_letter",
        )

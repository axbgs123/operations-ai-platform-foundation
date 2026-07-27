from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.database import Base
from app.main import app
from app.core.operations_router import dispatch_operational_retry
from app.core.observability import (
    HIGH_CARDINALITY_LABELS,
    InMemoryOperationsStore,
    OperationalTask,
    OperationsService,
    RetryClass,
    TechnicalMetrics,
    calculate_retry_delay,
)
from app.core.security import WorkspaceContext
from app.modules.exports.models import (
    FullRestorePhase,
    FullRestoreStatus,
    RestoreJob,
)
from app.modules.generation.models import TextGenerationRun, TextGenerationRunStatus
from app.modules.generation.text_service import (
    cancel_text_generation,
    create_text_generation,
)
from tests.imports.helpers import configured_client
from tests.generation.test_text_generation import _context as generation_context


def task(*, workspace_id=None, status="running", task_type="export") -> OperationalTask:
    now = datetime.now(UTC)
    return OperationalTask(
        task_id=uuid4(),
        task_type=task_type,
        workspace_id=workspace_id or uuid4(),
        status=status,
        progress=25,
        phase="writing",
        created_at=now,
        started_at=now,
        updated_at=now,
        completed_at=None,
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        cancelable=True,
        retryable=False,
        error_code=None,
        status_detail="处理中",
        request_id="req_01JSAFE000000000000000000",
        fencing_token=1,
    )


def test_cancel_is_idempotent_and_fences_old_worker() -> None:
    record = task()
    store = InMemoryOperationsStore([record])
    service = OperationsService(store)
    context = WorkspaceContext(record.workspace_id, uuid4(), "admin")

    first = service.cancel(
        context,
        task_type=record.task_type,
        task_id=record.task_id,
        idempotency_key="cancel-1",
    )
    second = service.cancel(
        context,
        task_type=record.task_type,
        task_id=record.task_id,
        idempotency_key="cancel-1",
    )

    assert first.status == second.status == "cancelled"
    assert not store.can_publish(record.task_id, fencing_token=1)
    assert len(store.events) == 1


def test_generation_optimistic_fence_prevents_old_worker_success_publish() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as creator:
        run, _ = create_text_generation(creator, generation_context())
        creator.commit()
        run_id = run.id

    worker = Session(engine, expire_on_commit=False)
    canceller = Session(engine, expire_on_commit=False)
    try:
        stale = worker.get(TextGenerationRun, run_id)
        assert stale is not None
        cancelled = cancel_text_generation(canceller, run_id)
        canceller.commit()
        assert cancelled.status is TextGenerationRunStatus.CANCELLED

        stale.status = TextGenerationRunStatus.SUCCEEDED
        stale.final_title = "不得发布的旧 Worker 标题"
        with pytest.raises(StaleDataError):
            worker.commit()
        worker.rollback()
    finally:
        worker.close()
        canceller.close()

    with Session(engine) as verifier:
        persisted = verifier.get(TextGenerationRun, run_id)
        assert persisted is not None
        assert persisted.status is TextGenerationRunStatus.CANCELLED
        assert persisted.final_title is None


def test_compensation_and_non_cancelable_states_are_protected() -> None:
    record = task(status="compensation_required")
    store = InMemoryOperationsStore([record])
    service = OperationsService(store)
    context = WorkspaceContext(record.workspace_id, uuid4(), "admin")

    with pytest.raises(ValueError, match="TASK_COMPENSATION_REQUIRED"):
        service.cancel(
            context,
            task_type=record.task_type,
            task_id=record.task_id,
            idempotency_key="cancel-1",
        )


def test_cross_workspace_is_not_found_and_editor_viewer_cannot_mutate() -> None:
    record = task()
    service = OperationsService(InMemoryOperationsStore([record]))
    for context in (
        WorkspaceContext(uuid4(), uuid4(), "admin"),
        WorkspaceContext(record.workspace_id, uuid4(), "editor"),
        WorkspaceContext(record.workspace_id, uuid4(), "viewer"),
    ):
        with pytest.raises(LookupError if context.role == "admin" else PermissionError):
            service.cancel(
                context,
                task_type=record.task_type,
                task_id=record.task_id,
                idempotency_key="cancel-1",
            )


def test_retry_policy_dead_letters_and_manual_retry_is_idempotent() -> None:
    failed = task(status="dead_letter")
    failed = failed.model_copy(
        update={"retryable": True, "retry_count": 3, "error_code": "STORAGE_TIMEOUT"}
    )
    store = InMemoryOperationsStore([failed])
    service = OperationsService(store)
    context = WorkspaceContext(failed.workspace_id, uuid4(), "admin")

    diagnostic = service.safe_diagnostic(context, failed.task_type, failed.task_id)
    assert diagnostic.status == "dead_letter"
    assert diagnostic.model_dump().keys() == {
        "error_code",
        "failure_stage",
        "retry_count",
        "last_attempt_at",
        "next_action",
        "request_id",
        "task_id",
        "summary",
        "status",
    }
    recovered = service.retry(
        context,
        task_type=failed.task_type,
        task_id=failed.task_id,
        idempotency_key="retry-dead-letter",
    )
    assert recovered.status == "retrying"

    retryable = failed.model_copy(update={"retry_count": 1})
    store = InMemoryOperationsStore([retryable])
    service = OperationsService(store)
    one = service.retry(
        context,
        task_type=retryable.task_type,
        task_id=retryable.task_id,
        idempotency_key="retry-1",
    )
    two = service.retry(
        context,
        task_type=retryable.task_type,
        task_id=retryable.task_id,
        idempotency_key="retry-1",
    )
    assert one.task_id == two.task_id
    assert len(store.events) == 1


def test_only_transient_errors_retry_with_bounded_exponential_jitter() -> None:
    assert RetryClass.classify("STORAGE_TIMEOUT") == "transient"
    assert RetryClass.classify("PERMISSION_DENIED") == "terminal"
    delays = [
        calculate_retry_delay(attempt, jitter=lambda: 0.5) for attempt in range(1, 8)
    ]
    assert delays == sorted(delays)
    assert delays[-1] <= timedelta(minutes=15)


def test_manual_retry_dispatches_the_new_executable_task(monkeypatch) -> None:
    from app.modules.exports import tasks as export_tasks

    retried = task(status="retrying", task_type="export")
    dispatched: list[UUID] = []
    monkeypatch.setattr(export_tasks, "enqueue_export", dispatched.append)

    dispatch_operational_retry(retried)

    assert dispatched == [retried.task_id]


def test_metrics_forbid_sensitive_and_high_cardinality_labels() -> None:
    assert HIGH_CARDINALITY_LABELS >= {
        "workspace_id",
        "member_id",
        "content_id",
        "request_id",
        "title",
        "url",
    }
    metrics = TechnicalMetrics()
    metrics.record(
        "tasks_total",
        labels={"task_type": "export", "status": "failed"},
    )
    with pytest.raises(ValueError, match="label"):
        metrics.record(
            "tasks_total",
            labels={"workspace_id": str(uuid4())},
        )


def test_operations_api_role_matrix_workspace_scope_and_append_only_cancel() -> None:
    with configured_client() as (admin, engine):
        workspace = admin.post("/v1/workspaces", json={"name": "运维测试"}).json()
        login = admin.post(
            "/v1/sessions/invite",
            json={"code": workspace["admin_code"], "display_name": "管理员"},
        ).json()
        workspace_id = UUID(workspace["workspace_id"])
        member_id = UUID(login["member_id"])
        csrf = login["csrf_token"]
        with Session(engine, expire_on_commit=False) as session:
            restore = RestoreJob(
                workspace_id=workspace_id,
                requested_by=member_id,
                target_workspace_id=workspace_id,
                mode="merge",
                idempotency_key="restore-ops-1",
                request_fingerprint="1" * 64,
                archive_sha256="2" * 64,
                archive_object_key=f"workspaces/{workspace_id}/staging/archive.zip",
                staging_prefix=f"workspaces/{workspace_id}/staging/restore/",
                status=FullRestoreStatus.QUEUED,
                phase=FullRestorePhase.UPLOADED,
                preview_id="3" * 64,
                manifest_fingerprint="4" * 64,
                preview_json={},
                object_plan=[],
                confirm_idempotency_key=None,
                claim_token=None,
                lease_expires_at=None,
                error_code=None,
                knowledge_index_message=None,
                completed_at=None,
            )
            session.add(restore)
            session.commit()
            task_id = restore.id

        listing = admin.get(
            f"/v1/workspaces/{workspace_id}/operations/tasks",
            params={"task_type": "restore"},
        )
        assert listing.status_code == 200, listing.text
        assert listing.json()["items"][0]["task_id"] == str(task_id)

        cancelled = admin.post(
            f"/v1/workspaces/{workspace_id}/operations/tasks/restore/{task_id}/cancel",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "cancel-restore-1",
            },
        )
        assert cancelled.status_code == 200, cancelled.text
        repeated = admin.post(
            f"/v1/workspaces/{workspace_id}/operations/tasks/restore/{task_id}/cancel",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "cancel-restore-1",
            },
        )
        assert repeated.status_code == 200

        code = admin.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "editor"},
        ).json()["code"]
        editor = TestClient(app)
        editor_login = editor.post(
            "/v1/sessions/invite",
            json={"code": code, "display_name": "编辑"},
        ).json()
        assert (
            editor.get(f"/v1/workspaces/{workspace_id}/operations/tasks").status_code
            == 200
        )
        assert editor.get(
            f"/v1/workspaces/{workspace_id}/operations/access"
        ).json() == {
            "role": "editor",
            "can_read": True,
            "can_operate": False,
        }
        assert (
            editor.post(
                f"/v1/workspaces/{workspace_id}/operations/tasks/restore/{task_id}/retry",
                headers={
                    "X-CSRF-Token": editor_login["csrf_token"],
                    "Idempotency-Key": "retry-no-admin",
                },
            ).status_code
            == 403
        )

        viewer_code = admin.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "viewer"},
        ).json()["code"]
        viewer = TestClient(app)
        viewer.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "查看"},
        )
        assert viewer.get(
            f"/v1/workspaces/{workspace_id}/operations/access"
        ).json() == {
            "role": "viewer",
            "can_read": False,
            "can_operate": False,
        }
        assert (
            viewer.get(f"/v1/workspaces/{workspace_id}/operations/tasks").status_code
            == 403
        )
        assert (
            admin.get(
                f"/v1/workspaces/{uuid4()}/operations/tasks/restore/{task_id}"
            ).status_code
            == 404
        )

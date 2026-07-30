import csv
from datetime import UTC, datetime, timedelta, timezone
from io import StringIO
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy.orm import Session

from app.core.storage import StoredObject
from app.main import app
from app.modules.exports.models import ExportStatus, ExportTask
from app.modules.exports.router import get_export_enqueuer
from app.modules.exports.service import (
    process_export_task,
    recoverable_export_task_ids,
)
from app.modules.exports.tabular import (
    isoformat_preserving_timezone,
    safe_export_filename,
)
from app.modules.workspace.models import MemberRole, WorkspaceMember
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)


class MemoryExportStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.now = datetime(2026, 7, 26, 2, 0, tzinfo=UTC)

    def put_object(self, object_key: str, content: bytes, *, mime_type: str) -> None:
        self.objects[object_key] = (content, mime_type)

    def presign_download(self, object_key: str) -> tuple[str, datetime]:
        expires_at = self.now + timedelta(minutes=5)
        return (
            f"https://storage.test/download/{object_key}?expires=300&signature=test",
            expires_at,
        )

    def inspect_object(self, object_key: str) -> StoredObject | None:
        stored = self.objects.get(object_key)
        if stored is None:
            return None
        return StoredObject(size=len(stored[0]), mime_type=stored[1])

    def issue_upload(self, **metadata):  # pragma: no cover - not part of export
        raise AssertionError("exports never issue upload grants")

    def verify_upload_token(self, token: str):  # pragma: no cover
        raise AssertionError("exports never accept upload tokens")


def _add_snapshot(
    client: TestClient,
    *,
    content: dict,
    csrf: str,
    metrics: list[dict],
) -> None:
    response = client.post(
        f"/v1/contents/{content['id']}/snapshots",
        headers={"X-CSRF-Token": csrf},
        json={
            "collected_at": content["published_at"],
            "source": "manual",
            "metrics": metrics,
        },
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()
    confirmed = client.post(
        f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200, confirmed.text


def _login_role(
    admin: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    role: str,
) -> TestClient:
    code = admin.post(
        f"/v1/workspaces/{workspace_id}/members/codes",
        headers={"X-CSRF-Token": csrf},
        json={"role": role},
    ).json()["code"]
    client = TestClient(app)
    response = client.post(
        "/v1/sessions/invite",
        json={"code": code, "display_name": f"合成{role}"},
    )
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def test_csv_export_is_workspace_scoped_deterministic_and_formula_safe() -> None:
    queued: list[UUID] = []
    storage = MemoryExportStorage()
    with configured_client() as (client, engine):
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        from app.core.storage import get_storage

        app.dependency_overrides[get_storage] = lambda: storage
        workspace_id, csrf, douyin = create_workspace_account(client)
        douyin_content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=douyin,
            title="=HYPERLINK(\"https://invalid.test\",\"合成\")",
            work_url="https://example.test/douyin-synthetic",
        )
        changed = client.patch(
            f"/v1/contents/{douyin_content['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "title": "发布后编辑标题",
                "body": "发布后编辑正文",
            },
        )
        assert changed.status_code == 200, changed.text
        _add_snapshot(
            client,
            content=douyin_content,
            csrf=csrf,
            metrics=[
                {"key": "views", "raw_value": 120},
                {"key": "likes", "raw_value": None},
            ],
        )
        xhs = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers={"X-CSRF-Token": csrf},
            json={
                "platform": "xiaohongshu",
                "name": "小红书合成账号",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        ).json()
        xhs_content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=xhs,
            title="小红书合成标题",
            work_url="https://example.test/xhs-synthetic",
        )
        _add_snapshot(
            client,
            content=xhs_content,
            csrf=csrf,
            metrics=[{"key": "impressions", "raw_value": 88}],
        )
        other_workspace, _, _ = create_workspace_account(
            TestClient(app),
            workspace_name="其他合成工作区",
        )

        created = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "csv-export-1",
            },
            json={"kind": "csv"},
        )

        assert created.status_code == 202, created.text
        task_id = UUID(created.json()["id"])
        assert queued == [task_id]
        with Session(engine, expire_on_commit=False) as session:
            process_export_task(session, task_id, storage)
            session.commit()

        completed = client.get(
            f"/v1/workspaces/{workspace_id}/exports/{task_id}"
        )
        assert completed.status_code == 200, completed.text
        payload = completed.json()
        assert payload["status"] == "succeeded"
        assert payload["download_url"].startswith("https://storage.test/download/")
        assert "session" not in payload["download_url"].lower()
        assert "invite" not in payload["download_url"].lower()
        object_key = next(iter(storage.objects))
        csv_bytes, mime_type = storage.objects[object_key]
        assert mime_type == "text/csv"
        rows = list(csv.DictReader(StringIO(csv_bytes.decode("utf-8-sig"))))
        assert list(rows[0]) == [
            "content_id",
            "account_id",
            "platform",
            "content_type",
            "platform_content_id",
            "title",
            "body",
            "status",
            "work_url",
            "published_at",
            "snapshot_id",
            "collected_at",
            "source",
            "metric_key",
            "raw_value",
            "normalized_value",
            "ocr_confidence",
        ]
        assert [row["platform"] for row in rows] == [
            "douyin",
            "douyin",
            "xiaohongshu",
        ]
        assert rows[0]["title"].startswith("'=")
        assert rows[0]["body"] == "合成测试内容"
        assert rows[0]["work_url"] == "https://example.test/douyin-synthetic"
        assert rows[0]["platform_content_id"] == ""
        assert rows[0]["published_at"].endswith("+00:00")
        assert rows[0]["raw_value"] == ""
        assert rows[1]["raw_value"] == "120"
        assert rows[2]["metric_key"] == "impressions"
        assert all(row["content_id"] != other_workspace for row in rows)


def test_csv_export_is_idempotent_and_cross_workspace_is_hidden() -> None:
    queued: list[UUID] = []
    with configured_client() as (client, _):
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(client)
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "same-export",
        }
        first = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "csv"},
        )
        repeated = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "csv"},
        )
        conflict = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "markdown", "content_id": str(uuid4())},
        )

        assert first.status_code == repeated.status_code == 202
        assert first.json()["id"] == repeated.json()["id"]
        assert queued == [UUID(first.json()["id"])]
        assert conflict.status_code == 409

        other_workspace = client.post(
            "/v1/workspaces", json={"name": "隔离导出工作区"}
        ).json()
        other_login = TestClient(app)
        logged_in = other_login.post(
            "/v1/sessions/invite",
            json={
                "code": other_workspace["admin_code"],
                "display_name": "其他管理员",
            },
        )
        assert logged_in.status_code == 201
        hidden = other_login.get(
            f"/v1/workspaces/{other_workspace['workspace_id']}/exports/"
            f"{first.json()['id']}"
        )
        assert hidden.status_code == 404


def test_viewer_cannot_create_or_download_exports_while_editor_can() -> None:
    queued: list[UUID] = []
    with configured_client() as (admin, _):
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(admin)
        editor = _login_role(
            admin, workspace_id=workspace_id, csrf=csrf, role="editor"
        )
        viewer = _login_role(
            admin, workspace_id=workspace_id, csrf=csrf, role="viewer"
        )
        editor_created = editor.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={"Idempotency-Key": "editor-export"},
            json={"kind": "csv"},
        )
        viewer_created = viewer.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={"Idempotency-Key": "viewer-export"},
            json={"kind": "csv"},
        )

        assert editor_created.status_code == 202
        assert viewer_created.status_code == 403
        viewer_list = viewer.get(
            f"/v1/workspaces/{workspace_id}/exports"
        )
        assert viewer_list.status_code == 200
        assert viewer_list.json()["items"][0]["id"] == editor_created.json()["id"]
        assert viewer_list.json()["items"][0]["download_url"] is None
        assert (
            viewer.get(
                f"/v1/workspaces/{workspace_id}/exports/"
                f"{editor_created.json()['id']}"
            ).status_code
            == 403
        )
        editor.close()
        viewer.close()


def test_timezones_and_filenames_are_header_safe() -> None:
    original = datetime(2026, 7, 26, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    assert isoformat_preserving_timezone(original) == "2026-07-26T10:30:00+08:00"
    file_name = safe_export_filename("../../危险\r\nX-Injected: yes", "csv")
    assert file_name.endswith(".csv")
    assert "/" not in file_name
    assert "\\" not in file_name
    assert "\r" not in file_name
    assert "\n" not in file_name
    assert ":" not in file_name


@pytest.mark.parametrize(
    "value",
    [
        "\n=HYPERLINK(\"https://invalid.test\")",
        " \t+SUM(1,1)",
        "\v@IMPORTXML(\"https://invalid.test\")",
    ],
)
def test_csv_formula_injection_cannot_hide_behind_whitespace(value: str) -> None:
    from app.modules.exports.tabular import formula_safe_cell

    rendered = formula_safe_cell(value)
    assert rendered.startswith("'")
    assert rendered[1:] == value


def test_failed_export_never_exposes_a_partial_object() -> None:
    class FailingStorage(MemoryExportStorage):
        def put_object(
            self, object_key: str, content: bytes, *, mime_type: str
        ) -> None:
            raise RuntimeError("synthetic object storage outage")

    with configured_client() as (client, engine):
        queued: list[UUID] = []
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(client)
        response = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "failed-export",
            },
            json={"kind": "csv"},
        )
        task_id = UUID(response.json()["id"])
        with Session(engine, expire_on_commit=False) as session:
            process_export_task(session, task_id, FailingStorage())
            session.commit()
            task = session.get(ExportTask, task_id)
            assert task is not None
            assert task.status is ExportStatus.FAILED
            assert task.object_key is None
            assert task.file_name is None

        read = client.get(f"/v1/workspaces/{workspace_id}/exports/{task_id}")
        assert read.status_code == 200
        assert read.json()["download_url"] is None
        assert "outage" not in str(read.json()).lower()


def test_worker_rechecks_member_permission_before_writing_export() -> None:
    storage = MemoryExportStorage()
    with configured_client() as (client, engine):
        queued: list[UUID] = []
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(client)
        response = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "permission-recheck",
            },
            json={"kind": "csv"},
        )
        task_id = UUID(response.json()["id"])
        with Session(engine, expire_on_commit=False) as session:
            task = session.get(ExportTask, task_id)
            assert task is not None
            member = session.get(WorkspaceMember, task.requested_by)
            assert member is not None
            member.role = MemberRole.VIEWER
            session.commit()
            process_export_task(session, task_id, storage)
            session.commit()
            assert task.status is ExportStatus.FAILED
            assert task.error_code == "export_authorization_revoked"
            assert task.object_key is None
        assert storage.objects == {}


def test_broker_failure_can_be_retried_with_the_same_idempotency_key() -> None:
    attempts = 0
    queued: list[UUID] = []

    def flaky_enqueue(task_id: UUID) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("synthetic broker outage")
        queued.append(task_id)

    with configured_client() as (client, _):
        app.dependency_overrides[get_export_enqueuer] = lambda: flaky_enqueue
        workspace_id, csrf, _ = create_workspace_account(client)
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "retry-enqueue",
        }
        first = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "csv"},
        )
        retried = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "csv"},
        )

        assert first.status_code == 503
        assert retried.status_code == 202
        assert queued == [UUID(retried.json()["id"])]


def test_worker_claim_and_expired_lease_recovery_prevent_duplicate_writes() -> None:
    storage = MemoryExportStorage()
    with configured_client() as (client, engine):
        queued: list[UUID] = []
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(client)
        response = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "atomic-claim",
            },
            json={"kind": "csv"},
        )
        task_id = UUID(response.json()["id"])
        with Session(engine, expire_on_commit=False) as session:
            now = datetime.now(UTC)
            task = session.get(ExportTask, task_id)
            assert task is not None
            assert task.enqueued_at is not None
            assert task_id not in recoverable_export_task_ids(
                session, now=now
            )
            task.enqueued_at = None
            session.commit()
            assert task_id in recoverable_export_task_ids(
                session, now=now
            )
            task.status = ExportStatus.RUNNING
            task.lease_expires_at = now + timedelta(minutes=5)
            session.commit()

            process_export_task(session, task_id, storage)
            assert storage.objects == {}
            session.refresh(task)
            assert task.status is ExportStatus.RUNNING

            task.lease_expires_at = now - timedelta(seconds=1)
            session.commit()
            assert task_id in recoverable_export_task_ids(
                session, now=now
            )
            process_export_task(session, task_id, storage)
            session.commit()
            session.refresh(task)
            assert task.status is ExportStatus.SUCCEEDED
            assert len(storage.objects) == 1


def test_lost_worker_claim_cannot_publish_or_overwrite_newer_state() -> None:
    class TakeoverStorage(MemoryExportStorage):
        def __init__(self, session: Session, task_id: UUID) -> None:
            super().__init__()
            self.session = session
            self.task_id = task_id

        def put_object(
            self, object_key: str, content: bytes, *, mime_type: str
        ) -> None:
            super().put_object(object_key, content, mime_type=mime_type)
            task = self.session.get(ExportTask, self.task_id)
            assert task is not None
            task.status = ExportStatus.RUNNING
            task.claim_token = "newer-worker-claim"
            task.object_key = None
            self.session.flush()

    with configured_client() as (client, engine):
        queued: list[UUID] = []
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(client)
        response = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "fenced-worker",
            },
            json={"kind": "csv"},
        )
        task_id = UUID(response.json()["id"])
        with Session(engine, expire_on_commit=False) as session:
            storage = TakeoverStorage(session, task_id)
            process_export_task(session, task_id, storage)
            session.commit()
            task = session.get(ExportTask, task_id)
            assert task is not None
            assert task.status is ExportStatus.RUNNING
            assert task.claim_token == "newer-worker-claim"
            assert task.object_key is None


def test_empty_published_body_never_falls_back_to_unpublished_draft() -> None:
    storage = MemoryExportStorage()
    with configured_client() as (client, engine):
        queued: list[UUID] = []
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, account = create_workspace_account(client)
        created = client.post(
            "/v1/contents",
            headers={"X-CSRF-Token": csrf},
            json={
                "workspace_id": workspace_id,
                "account_id": account["id"],
                "platform": "douyin",
                "content_type": "video",
                "title": "空正文发布测试",
                "body": "",
            },
        ).json()
        published = client.patch(
            f"/v1/contents/{created['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "published"},
        )
        assert published.status_code == 200
        edited = client.patch(
            f"/v1/contents/{created['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"body": "未发布的后续草稿正文"},
        )
        assert edited.status_code == 200
        export = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "empty-published-body",
            },
            json={"kind": "csv"},
        )
        task_id = UUID(export.json()["id"])
        with Session(engine) as session:
            process_export_task(session, task_id, storage)
            session.commit()
        rows = list(
            csv.DictReader(
                StringIO(next(iter(storage.objects.values()))[0].decode("utf-8-sig"))
            )
        )
        exported = next(row for row in rows if row["content_id"] == created["id"])
        assert exported["body"] == ""
        assert "未发布的后续草稿正文" not in str(rows)


def test_export_task_list_is_workspace_scoped_stable_and_paginated() -> None:
    queued: list[UUID] = []
    with configured_client() as (client, _):
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _ = create_workspace_account(client)
        other_client = TestClient(app)
        other_workspace_id, _, _ = create_workspace_account(
            other_client,
            workspace_name="其他导出工作区",
        )
        for index, kind in enumerate(("csv", "json", "zip")):
            response = client.post(
                f"/v1/workspaces/{workspace_id}/exports",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": f"list-export-{index}",
                },
                json={"kind": kind},
            )
            assert response.status_code == 202, response.text

        first = client.get(
            f"/v1/workspaces/{workspace_id}/exports?page=1&page_size=2"
        )
        second = client.get(
            f"/v1/workspaces/{workspace_id}/exports?page=2&page_size=2"
        )
        assert first.status_code == 200, first.text
        assert first.json()["total"] == 3
        assert first.json()["page"] == 1
        assert len(first.json()["items"]) == 2
        assert len(second.json()["items"]) == 1
        assert first.json()["items"][0]["id"] != first.json()["items"][1]["id"]
        assert all(item["download_url"] is None for item in first.json()["items"])
        assert "object_key" not in first.text
        assert client.get(
            f"/v1/workspaces/{workspace_id}/exports?page_size=101"
        ).status_code == 422
        assert other_client.get(
            f"/v1/workspaces/{workspace_id}/exports"
        ).status_code == 404
        assert client.get(
            f"/v1/workspaces/{other_workspace_id}/exports"
        ).status_code == 404
        app.dependency_overrides.clear()

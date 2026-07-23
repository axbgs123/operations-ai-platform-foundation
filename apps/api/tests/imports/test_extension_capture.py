from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.capture_service import transition_task
from tests.imports.helpers import configured_client


def _bind(client: TestClient, invite_code: str) -> str:
    response = client.post(
        "/v1/extension/bind",
        json={"invite_code": invite_code, "client_id": "capture-test"},
        headers={
            "Idempotency-Key": "capture-bind",
            "X-Extension-Client": "capture-test",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_extension_capture_task_is_staged_idempotently_and_never_confirmed_by_token() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "截图暂存工作区"}).json()
        token = _bind(client, workspace["admin_code"])
        headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "upload-1"}
        payload = {
            "platform": "douyin",
            "page_version": "douyin-creator-v1",
            "page_identifier": "synthetic-detail-1",
            "collected_at": datetime.now(UTC).isoformat(),
            "screenshot_data_url": "data:image/png;base64,U1lOVEhFVElD",
        }

        first = client.post(
            f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
            json=payload,
            headers=headers,
        )
        assert first.status_code == 202, first.text
        task = first.json()
        assert task["status"] in {"queued", "running", "succeeded"}
        assert task["review_url"]
        assert "SYNTHETIC" not in first.text

        duplicate = client.post(
            f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
            json=payload,
            headers=headers,
        )
        assert duplicate.status_code == 202
        assert duplicate.json()["task_id"] == task["task_id"]
        conflict_payload = {**payload, "screenshot_data_url": "data:image/png;base64,T1RIRVI="}
        conflict = client.post(
            f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
            json=conflict_payload,
            headers=headers,
        )
        assert conflict.status_code == 409

        read = client.get(
            f"/v1/extension/capture-tasks/{task['task_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert read.status_code == 200
        assert read.json()["workspace_id"] == workspace["workspace_id"]

        forbidden = client.post(
            f"/v1/extension/capture-tasks/{task['task_id']}/confirm",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert forbidden.status_code == 403

        with engine.connect() as connection:
            assert connection.execute(
                CaptureTask.__table__.select()
            ).fetchone() is not None


def test_extension_capture_task_is_workspace_scoped_and_rejects_invalid_transitions() -> None:
    with configured_client() as (client, _):
        first = client.post("/v1/workspaces", json={"name": "截图工作区A"}).json()
        second = client.post("/v1/workspaces", json={"name": "截图工作区B"}).json()
        token = _bind(client, first["admin_code"])
        response = client.post(
            f"/v1/extension/workspaces/{first['workspace_id']}/capture-tasks",
            json={
                "platform": "douyin",
                "page_version": "douyin-creator-v1",
                "page_identifier": "synthetic-detail-2",
                "collected_at": datetime.now(UTC).isoformat(),
                "screenshot_data_url": "data:image/png;base64,U1lOVEhFVElD",
            },
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "upload-2"},
        )
        task_id = response.json()["task_id"]
        cross = client.get(
            f"/v1/extension/workspaces/{second['workspace_id']}/capture-tasks/{task_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cross.status_code == 404

def test_capture_task_state_machine_rejects_illegal_transitions() -> None:
    task = type("Task", (), {"status": CaptureTaskStatus.QUEUED})()
    transition_task(task, CaptureTaskStatus.RUNNING)
    assert task.status == CaptureTaskStatus.RUNNING
    transition_task(task, CaptureTaskStatus.RETRYING)
    assert task.status == CaptureTaskStatus.RETRYING
    import pytest

    with pytest.raises(ValueError, match="illegal capture task transition"):
        transition_task(task, CaptureTaskStatus.SUCCEEDED)


def test_only_web_editor_or_admin_can_confirm_into_a_formal_snapshot() -> None:
    with configured_client() as (client, _):
        workspace = client.post("/v1/workspaces", json={"name": "人工确认工作区"}).json()
        login = client.post(
            "/v1/sessions/invite",
            json={"code": workspace["admin_code"], "display_name": "确认管理员"},
        ).json()
        workspace_id = workspace["workspace_id"]
        csrf = login["csrf_token"]
        account = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers={"X-CSRF-Token": csrf},
            json={
                "platform": "douyin",
                "name": "合成确认账号",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        ).json()
        token = _bind(client, workspace["admin_code"])

        response = client.post(
            f"/v1/extension/workspaces/{workspace_id}/capture-tasks",
            json={
                "platform": account["platform"],
                "page_version": "douyin-creator-v1",
                "page_identifier": "synthetic-review-1",
                "collected_at": datetime.now(UTC).isoformat(),
                "screenshot_data_url": "data:image/png;base64,U1lOVEhFVElD",
            },
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "review-1"},
        )
        task_id = response.json()["task_id"]
        confirmed = client.post(
            f"/v1/imports/capture-tasks/{task_id}/confirm",
            json={"corrections": {"views": "1200"}},
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert len(confirmed.json()["formal_snapshot_ids"]) == 1

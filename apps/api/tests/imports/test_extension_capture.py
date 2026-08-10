from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.storage import StoredObject, get_storage
from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.capture_service import object_digest, transition_task
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
            "capture_mode": "visible",
            "complete": True,
            "stop_reason": "visible",
            "slice_count": 1,
        }

        first = client.post(
            f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
            json=payload,
            headers=headers,
        )
        assert first.status_code == 202, first.text
        task = first.json()
        assert task["status"] in {"queued", "running", "succeeded"}
        assert task["platform"] == "douyin"
        assert task["page_version"] == "douyin-creator-v1"
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


def test_extension_capture_contract_accepts_and_persists_bounded_full_page_metadata() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "整页合同工作区"}).json()
        token = _bind(client, workspace["admin_code"])
        payload = {
            "platform": "douyin",
            "page_version": "douyin-creator-v1",
            "page_identifier": "synthetic-full-page",
            "collected_at": datetime.now(UTC).isoformat(),
            "screenshot_data_url": "data:image/png;base64,U1lOVEhFVElD",
            "capture_mode": "full-page",
            "complete": False,
            "stop_reason": "slice-limit",
            "slice_count": 3,
        }
        response = client.post(
            f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
            json=payload,
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "full-page-1"},
        )

        assert response.status_code == 202, response.text
        assert response.json()["capture_metadata"] == {
            "capture_mode": "full-page",
            "complete": False,
            "stop_reason": "slice-limit",
            "slice_count": 3,
        }
        with Session(engine) as session:
            task = session.get(CaptureTask, UUID(response.json()["task_id"]))
            assert task is not None
            assert task.capture_metadata == response.json()["capture_metadata"]


def test_extension_capture_contract_rejects_inconsistent_or_out_of_bounds_metadata() -> None:
    with configured_client() as (client, _):
        workspace = client.post("/v1/workspaces", json={"name": "整页合同校验工作区"}).json()
        token = _bind(client, workspace["admin_code"])
        base = {
            "platform": "douyin",
            "page_version": "douyin-creator-v1",
            "page_identifier": "synthetic-invalid-full-page",
            "collected_at": datetime.now(UTC).isoformat(),
            "screenshot_data_url": "data:image/png;base64,U1lOVEhFVElD",
        }
        for index, metadata in enumerate((
            {"capture_mode": "full-page", "complete": True, "stop_reason": "slice-limit", "slice_count": 3},
            {"capture_mode": "visible", "complete": False, "stop_reason": "visible", "slice_count": 1},
            {"capture_mode": "region", "complete": True, "stop_reason": "region", "slice_count": 31},
        )):
            response = client.post(
                f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
                json={**base, **metadata},
                headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"invalid-metadata-{index}"},
            )
            assert response.status_code == 422


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
                "capture_mode": "visible",
                "complete": True,
                "stop_reason": "visible",
                "slice_count": 1,
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


def test_non_mock_capture_freezes_vision_binding_and_discloses_region(
    monkeypatch,
) -> None:
    from app.core.config import Settings
    from app.main import app
    from app.modules.imports.capture_service import get_capture_enqueuer
    from app.modules.models.catalog import QIANWEN_OCR_MODEL_ID
    import app.modules.imports.extension_router as extension_router

    monkeypatch.setattr(
        extension_router,
        "get_settings",
        lambda: Settings(app_mock_mode=False),
    )
    queued: list[object] = []
    stored: dict[str, tuple[bytes, str]] = {}

    class CaptureStorage:
        def put_object(
            self,
            object_key: str,
            content: bytes,
            *,
            mime_type: str,
        ) -> None:
            stored[object_key] = (content, mime_type)

        def inspect_object(self, object_key: str) -> StoredObject | None:
            item = stored.get(object_key)
            return (
                StoredObject(size=len(item[0]), mime_type=item[1])
                if item is not None
                else None
            )

        def get_object(self, object_key: str) -> bytes:
            return stored[object_key][0]

        def delete_object(self, object_key: str) -> None:
            stored.pop(object_key, None)

    app.dependency_overrides[get_capture_enqueuer] = lambda: queued.append
    app.dependency_overrides[get_storage] = CaptureStorage
    with configured_client() as (client, engine):
        workspace = client.post(
            "/v1/workspaces", json={"name": "真实视觉绑定合成工作区"}
        ).json()
        login = client.post(
            "/v1/sessions/invite",
            json={
                "code": workspace["admin_code"],
                "display_name": "视觉绑定管理员",
            },
        ).json()
        configured = client.post(
            f"/v1/workspaces/{workspace['workspace_id']}/model-configs",
            headers={"X-CSRF-Token": login["csrf_token"]},
            json={
                "provider": "qianwen",
                "model_id": QIANWEN_OCR_MODEL_ID,
                "region": "cn-beijing",
                "provider_workspace_id": "llm-abcd1234",
                "capabilities": ["vision"],
                "status": "experimental",
                "api_key": "sk-synthetic-never-real",
            },
        )
        assert configured.status_code == 201, configured.text
        token = _bind(client, workspace["admin_code"])
        response = client.post(
            f"/v1/extension/workspaces/{workspace['workspace_id']}/capture-tasks",
            json={
                "platform": "douyin",
                "page_version": "douyin-creator-v1",
                "page_identifier": "synthetic-real-binding",
                "collected_at": datetime.now(UTC).isoformat(),
                "screenshot_data_url": "data:image/png;base64,U1lOVEhFVElD",
                "capture_mode": "visible",
                "complete": True,
                "stop_reason": "visible",
                "slice_count": 1,
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": "real-binding-1",
            },
        )
        assert response.status_code == 202, response.text
        assert response.json()["provider_mode"] == "qianwen"
        assert response.json()["region"] == "cn-beijing"
        assert [str(item) for item in queued] == [response.json()["task_id"]]
        with engine.connect() as connection:
            row = connection.execute(CaptureTask.__table__.select()).mappings().one()
            assert str(row["model_config_id"]) == configured.json()["id"]
            assert row["model_id"] == QIANWEN_OCR_MODEL_ID
            assert row["contract_version"] == "qwen-ocr-advanced-v1"
            assert stored[row["object_key"]][0] == b"SYNTHETIC"


def test_only_web_editor_or_admin_can_confirm_into_a_formal_snapshot() -> None:
    with configured_client() as (client, engine):
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
        other_account = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers={"X-CSRF-Token": csrf},
            json={
                "platform": "xiaohongshu",
                "name": "错误平台合成账号",
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
                    "capture_mode": "visible",
                    "complete": True,
                    "stop_reason": "visible",
                    "slice_count": 1,
            },
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "review-1"},
        )
        task_id = response.json()["task_id"]
        with Session(engine) as session:
            staged_task = session.get(CaptureTask, UUID(task_id))
            assert staged_task is not None
            assert object_digest(staged_task) is not None
        mismatch = client.post(
            f"/v1/imports/capture-tasks/{task_id}/confirm",
            json={
                "account_id": other_account["id"],
                "corrections": {"views": "1200"},
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert mismatch.status_code == 404
        confirmed = client.post(
            f"/v1/imports/capture-tasks/{task_id}/confirm",
            json={
                "account_id": account["id"],
                "corrections": {"views": "1200"},
            },
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmed.status_code == 200, confirmed.text
        assert len(confirmed.json()["formal_snapshot_ids"]) == 1
        with Session(engine) as session:
            confirmed_task = session.get(CaptureTask, UUID(task_id))
            assert confirmed_task is not None
            assert object_digest(confirmed_task) is None

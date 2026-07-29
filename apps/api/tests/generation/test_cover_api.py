from uuid import UUID

from fastapi.testclient import TestClient

from app.main import app
from app.modules.generation.tasks import get_cover_generation_enqueuer
from tests.content.test_content_detail import (
    configured_client,
    create_admin_and_account,
)


def _create_content(
    client: TestClient,
    workspace_id: str,
    csrf: str,
    account_id: str,
) -> str:
    response = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace_id,
            "account_id": account_id,
            "platform": "douyin",
            "content_type": "video",
            "title": "合成封面 API 验收",
            "body": "只使用 Mock Provider 和合成数据。",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_cover_run_api_exposes_all_modes_without_leaking_object_keys() -> None:
    queued: list[UUID] = []
    with configured_client() as client:
        app.dependency_overrides[get_cover_generation_enqueuer] = (
            lambda: queued.append
        )
        workspace_id, csrf, account = create_admin_and_account(client)
        content_id = _create_content(
            client,
            workspace_id,
            csrf,
            account["id"],
        )
        model_response = client.post(
            f"/v1/workspaces/{workspace_id}/model-configs",
            headers={"X-CSRF-Token": csrf},
            json={
                "provider": "qianwen",
                "model_id": "qwen-image-2.0-pro-2026-06-22",
                "region": "cn-beijing",
                "provider_workspace_id": "llm-syntheticcover",
                "capabilities": ["image"],
                "status": "experimental",
                "api_key": "synthetic-test-only-key",
            },
        )
        assert model_response.status_code == 201, model_response.text
        model_config_id = model_response.json()["id"]

        run_ids: list[UUID] = []
        for mode in ("template", "ai_visual", "hybrid", "custom"):
            payload = {
                "content_id": content_id,
                "request": {
                    "mode": mode,
                    "size": {"width": 1080, "height": 1440},
                    "prompt": "synthetic AI technology cover",
                    "headline": "AI 科技观察",
                    "brand_name": "合成品牌",
                    "model_config_id": None,
                    "image_parameters": (
                        {"seed": 29} if mode == "custom" else {}
                    ),
                },
            }
            if mode != "template":
                payload["request"]["model_config_id"] = model_config_id
            response = client.post(
                f"/v1/workspaces/{workspace_id}/generation/cover-runs",
                headers={
                    "X-CSRF-Token": csrf,
                    "Idempotency-Key": f"cover-api-{mode}",
                },
                json=payload,
            )
            assert response.status_code == 202, response.text
            body = response.json()
            run_ids.append(UUID(body["id"]))
            assert body["cover_mode"] == mode
            assert body["status"] == "queued"
            assert "object_key" not in response.text
            assert "prompt" not in response.text
            read = client.get(
                (
                    f"/v1/workspaces/{workspace_id}/generation/"
                    f"cover-runs/{body['id']}"
                )
            )
            assert read.status_code == 200

        assert queued == run_ids

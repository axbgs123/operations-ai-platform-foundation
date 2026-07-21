from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_public_demo_exposes_only_immutable_synthetic_seed_data() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/demo/workspace")

        assert response.status_code == 200
        payload = response.json()
        assert payload["synthetic"] is True
        assert payload["label"] == "示例数据"
        assert {account["platform"] for account in payload["accounts"]} == {
            "douyin",
            "xiaohongshu",
        }
        assert all(account["synthetic"] is True for account in payload["accounts"])
        assert all(
            post["synthetic"] is True
            for account in payload["accounts"]
            for post in account["posts"]
        )

        assert client.get(f"/v1/demo/workspaces/{uuid4()}").status_code == 404
        assert client.post("/v1/demo/uploads").status_code == 403
        assert client.patch("/v1/demo/workspace", json={"name": "篡改"}).status_code == 403

        unchanged = client.get("/v1/demo/workspace").json()
        assert unchanged == payload

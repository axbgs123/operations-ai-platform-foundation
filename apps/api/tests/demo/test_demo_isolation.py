from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.demo_seed import seed_demo
from app.main import app


pytestmark = pytest.mark.isolation


def test_public_demo_exposes_only_immutable_synthetic_seed_data() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_demo(session)
        session.commit()

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as client:
            response = client.get("/v1/demo/workspace")

            assert response.status_code == 200
            payload = response.json()
            assert payload["synthetic"] is True
            assert payload["label"] == "示例数据 / Mock 数据"
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
    finally:
        app.dependency_overrides.clear()

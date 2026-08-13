import base64
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from uuid import UUID

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.hotspots.models import HotspotCaptureTask
from app.modules.hotspots.service import extract_candidates, normalize_source_url
from app.modules.workspace.router import invite_attempts


def _image_data_url(color: str = "white") -> str:
    image = Image.new("RGB", (32, 24), color=color)
    output = BytesIO()
    image.save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode()
    return f"data:image/png;base64,{encoded}"


@contextmanager
def _client() -> Iterator[tuple[TestClient, object]]:
    invite_attempts.clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    def override_session() -> Iterator[Session]:
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, engine
    finally:
        app.dependency_overrides.clear()


def _login_admin(client: TestClient, name: str) -> tuple[str, str]:
    workspace = client.post("/v1/workspaces", json={"name": name}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={
            "code": workspace["admin_code"],
            "display_name": f"{name}管理员",
        },
    ).json()
    return workspace["workspace_id"], login["csrf_token"]


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "target_platform": "douyin",
        "source_url": "https://example.com/hot-ranking?day=today#ignored",
        "page_title": "合成热点榜",
        "collected_at": "2026-08-13T03:00:00+08:00",
        "completeness": "full_page_complete",
        "screenshot_data_url": _image_data_url(),
    }
    payload.update(changes)
    return payload


def test_candidate_extraction_and_source_url_are_deterministic() -> None:
    assert extract_candidates(
        ["1 第一条热点 900万", "2 第二条热点", "2 第二条热点"]
    ) == [
        {
            "position": 1,
            "rank": 1,
            "topic": "第一条热点",
            "heat": "900万",
            "ocr_text_index": 0,
        },
        {
            "position": 2,
            "rank": 2,
            "topic": "第二条热点",
            "heat": None,
            "ocr_text_index": 1,
        },
    ]
    assert normalize_source_url(
        "https://Example.com/rank?q=1#section"
    ) == ("https://example.com/rank?q=1", "example.com")


def test_hotspot_capture_requires_review_and_creates_immutable_snapshot() -> None:
    with _client() as (client, engine):
        workspace_id, csrf = _login_admin(client, "热点合成工作区")
        created = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "hotspot-capture-1",
            },
            json=_payload(),
        )
        assert created.status_code == 202, created.text
        capture = created.json()
        assert capture["status"] == "review_ready"
        assert capture["source_url"] == "https://example.com/hot-ranking?day=today"
        assert len(capture["candidates"]) == 3
        for forbidden in ("screenshot_data_url", "object_key", "base64"):
            assert forbidden not in created.text

        repeated = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "hotspot-capture-1",
            },
            json=_payload(),
        )
        assert repeated.status_code == 202
        assert repeated.json()["id"] == capture["id"]

        conflict = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "hotspot-capture-1",
            },
            json=_payload(page_title="另一张截图"),
        )
        assert conflict.status_code == 409

        confirmation = {
            "entries": [
                {
                    "rank": 1,
                    "topic": "AI 视频生成更新",
                    "heat": "982万",
                    "selected": True,
                },
                {
                    "rank": 2,
                    "topic": "多模态智能体落地",
                    "heat": "765万",
                    "selected": True,
                },
            ]
        }
        confirmed = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures/{capture['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json=confirmation,
        )
        assert confirmed.status_code == 200, confirmed.text
        snapshot = confirmed.json()
        assert snapshot["entries"][0]["topic"] == "AI 视频生成更新"
        assert len(snapshot["entries"]) == 2

        same_confirmation = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures/{capture['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json=confirmation,
        )
        assert same_confirmation.status_code == 200
        assert same_confirmation.json()["id"] == snapshot["id"]

        changed_confirmation = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures/{capture['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={
                "entries": [
                    {"rank": 1, "topic": "被替换的热点", "selected": True}
                ]
            },
        )
        assert changed_confirmation.status_code == 409

        listed = client.get(
            f"/v1/workspaces/{workspace_id}/hotspots/snapshots",
            params={"target_platform": "douyin"},
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [snapshot["id"]]
        isolated = client.get(
            f"/v1/workspaces/{workspace_id}/hotspots/snapshots",
            params={"target_platform": "xiaohongshu"},
        )
        assert isolated.json() == []
        with Session(engine) as session:
            task = session.scalar(
                select(HotspotCaptureTask).where(
                    HotspotCaptureTask.id == UUID(capture["id"])
                )
            )
            assert task is not None
            assert task.object_deleted_at is not None


def test_viewer_cannot_capture_and_cross_workspace_capture_is_hidden() -> None:
    with _client() as (client, _):
        workspace_a, admin_csrf = _login_admin(client, "热点权限 A")
        created = client.post(
            f"/v1/workspaces/{workspace_a}/hotspots/captures",
            headers={
                "X-CSRF-Token": admin_csrf,
                "Idempotency-Key": "capture-a",
            },
            json=_payload(),
        )
        capture_id = created.json()["id"]
        viewer_code = client.post(
            f"/v1/workspaces/{workspace_a}/members/codes",
            headers={"X-CSRF-Token": admin_csrf},
            json={"role": "viewer"},
        ).json()["code"]
        viewer = client.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "热点只读成员"},
        ).json()
        denied = client.post(
            f"/v1/workspaces/{workspace_a}/hotspots/captures",
            headers={
                "X-CSRF-Token": viewer["csrf_token"],
                "Idempotency-Key": "viewer-capture",
            },
            json=_payload(),
        )
        assert denied.status_code == 403
        readable = client.get(
            f"/v1/workspaces/{workspace_a}/hotspots/captures/{capture_id}"
        )
        assert readable.status_code == 200

        workspace_b, _ = _login_admin(client, "热点权限 B")
        hidden = client.get(
            f"/v1/workspaces/{workspace_a}/hotspots/captures/{capture_id}"
        )
        assert workspace_b != workspace_a
        assert hidden.status_code == 404


def test_hotspot_capture_rejects_non_https_source() -> None:
    with _client() as (client, _):
        workspace_id, csrf = _login_admin(client, "热点 URL 工作区")
        response = client.post(
            f"/v1/workspaces/{workspace_id}/hotspots/captures",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "unsafe-url",
            },
            json=_payload(source_url="http://127.0.0.1/private"),
        )
        assert response.status_code == 422

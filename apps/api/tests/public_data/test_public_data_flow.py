from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.metrics.models import DataSnapshot, SnapshotMetricValue, SnapshotSource
from app.modules.public_data.models import (
    PublicCollectionJob,
    PublicDataProviderConfig,
    PublicObservation,
)
from app.modules.workspace.router import invite_attempts


@contextmanager
def configured_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    invite_attempts.clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()


def _workspace_account_content(
    client: TestClient,
) -> tuple[str, str, dict[str, object]]:
    workspace = client.post("/v1/workspaces", json={"name": "公开数据测试"}).json()
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "管理员"},
    ).json()
    csrf = login["csrf_token"]
    account = client.post(
        f"/v1/workspaces/{workspace['workspace_id']}/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": "douyin",
            "name": "测试账号",
            "objectives": ["engagement"],
            "metric_weights": {"likes": 1},
            "benchmark_sample_size": 30,
        },
    ).json()
    content = client.post(
        "/v1/contents",
        headers={"X-CSRF-Token": csrf},
        json={
            "workspace_id": workspace["workspace_id"],
            "account_id": account["id"],
            "platform": "douyin",
            "content_type": "video",
            "title": "公开作品",
            "body": "人工合成正文",
        },
    ).json()
    return workspace["workspace_id"], csrf, content


def test_config_binding_schedule_and_manual_collection(monkeypatch) -> None:
    with configured_client() as (client, factory):
        workspace_id, csrf, content = _workspace_account_content(client)
        headers = {"X-CSRF-Token": csrf}

        saved = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/provider",
            headers=headers,
            json={
                "api_key": "mock-tikhub-key",
                "endpoint_region": "china",
                "daily_request_limit": 30,
            },
        )
        assert saved.status_code == 200
        assert saved.json()["has_api_key"] is True
        assert "api_key" not in saved.json()

        tested = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/provider/test",
            headers=headers,
        )
        assert tested.status_code == 200
        assert tested.json()["connected"] is True

        published_at = datetime.now(UTC) - timedelta(minutes=20)
        bound = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/contents/{content['id']}/binding",
            headers=headers,
            json={
                "public_url": "https://www.douyin.com/video/73000123456789",
                "published_at": published_at.isoformat(),
            },
        )
        assert bound.status_code == 200
        payload = bound.json()
        assert payload["platform_content_id"] == "73000123456789"
        assert [job["target_window"] for job in payload["jobs"]] == [
            "1h",
            "24h",
            "72h",
            "7d",
        ]
        usage = client.get(f"/v1/workspaces/{workspace_id}/public-data/provider").json()
        assert usage["daily_requests_used"] == 2

        executed: list[UUID] = []
        monkeypatch.setattr(
            "app.modules.public_data.router.run_collection_job",
            lambda job_id: executed.append(job_id),
        )
        manual = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/contents/{content['id']}/collect-now",
            headers=headers,
        )
        assert manual.status_code == 202
        assert manual.json()["target_window"].startswith("manual-")
        assert executed == [UUID(manual.json()["id"])]

        monkeypatch.setattr("app.modules.public_data.service.SessionFactory", factory)
        from app.modules.public_data.service import run_collection_job

        run_collection_job(UUID(manual.json()["id"]))
        with factory() as session:
            job = session.get(PublicCollectionJob, UUID(manual.json()["id"]))
            assert job is not None
            assert job.status.value == "succeeded"
            snapshot = session.get(DataSnapshot, job.snapshot_id)
            assert snapshot is not None
            assert snapshot.source is SnapshotSource.PUBLIC_API
            assert snapshot.confirmed is True
            values = list(
                session.scalars(
                    select(SnapshotMetricValue).where(
                        SnapshotMetricValue.snapshot_id == snapshot.id
                    )
                )
            )
            assert {value.metric_key for value in values} == {
                "views",
                "likes",
                "comments",
                "favorites",
                "shares",
            }
            observation = session.scalar(
                select(PublicObservation).where(
                    PublicObservation.binding_id == job.binding_id
                )
            )
            assert observation is not None
            assert observation.raw_sha256
            assert observation.normalized_metrics["likes"] == 128
            assert (
                session.scalar(
                    select(PublicDataProviderConfig.daily_requests_used).where(
                        PublicDataProviderConfig.workspace_id == UUID(workspace_id)
                    )
                )
                == 3
            )


def test_binding_rejects_future_time_and_cross_platform_link() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, content = _workspace_account_content(client)
        headers = {"X-CSRF-Token": csrf}

        future = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/contents/{content['id']}/binding",
            headers=headers,
            json={
                "public_url": "https://www.douyin.com/video/73000123456789",
                "published_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            },
        )
        assert future.status_code == 422
        assert "不能晚于当前时间" in future.json()["detail"]

        wrong_platform = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/contents/{content['id']}/binding",
            headers=headers,
            json={
                "public_url": "https://www.xiaohongshu.com/explore/123456789012",
                "published_at": datetime.now(UTC).isoformat(),
            },
        )
        assert wrong_platform.status_code == 422
        assert "平台不匹配" in wrong_platform.json()["detail"]


def test_daily_limit_counts_connection_and_blocks_more_provider_calls() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, content = _workspace_account_content(client)
        headers = {"X-CSRF-Token": csrf}
        saved = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/provider",
            headers=headers,
            json={
                "api_key": "mock-tikhub-key",
                "endpoint_region": "china",
                "daily_request_limit": 1,
            },
        )
        assert saved.status_code == 200
        tested = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/provider/test",
            headers=headers,
        )
        assert tested.status_code == 200

        blocked = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/contents/{content['id']}/binding",
            headers=headers,
            json={
                "public_url": "https://www.douyin.com/video/73000123456789",
                "published_at": datetime.now(UTC).isoformat(),
            },
        )
        assert blocked.status_code == 429
        assert blocked.json()["detail"] == "PUBLIC_PROVIDER_DAILY_LIMIT_REACHED"

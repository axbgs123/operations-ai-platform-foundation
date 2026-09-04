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
        assert all(len(job["target_window"]) <= 40 for job in payload["jobs"])
        usage = client.get(f"/v1/workspaces/{workspace_id}/public-data/provider").json()
        assert usage["daily_requests_used"] == 2

        late_bound = client.put(
            f"/v1/workspaces/{workspace_id}/public-data/contents/{content['id']}/binding",
            headers=headers,
            json={
                "public_url": "https://www.douyin.com/video/73000123456789",
                "platform_content_id": "73000123456789",
                "published_at": (
                    datetime.now(UTC) - timedelta(hours=2)
                ).isoformat(),
            },
        )
        assert late_bound.status_code == 200
        late_labels = [
            job["target_window"]
            for job in late_bound.json()["jobs"]
            if job["target_window"].startswith("late-")
        ]
        assert len(late_labels) == 1
        assert len(late_labels[0]) <= 40

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
        assert len(manual.json()["target_window"]) <= 40
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
                    == 4
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


def test_competitor_comment_demand_and_daily_report_flow() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, _ = _workspace_account_content(client)
        headers = {"X-CSRF-Token": csrf}

        created = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/competitors",
            headers=headers,
            json={
                "platform": "douyin",
                "name": "同赛道账号",
                "public_url": "https://www.douyin.com/user/sec-user-1",
                "collection_interval_hours": 24,
            },
        )
        assert created.status_code == 200
        assert created.json()["platform_account_id"] == "sec-user-1"
        assert created.json()["latest_posts"] == []

        collected = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/competitors/{created.json()['id']}/collect",
            headers=headers,
        )
        assert collected.status_code == 200
        assert len(collected.json()["latest_posts"]) == 3
        assert collected.json()["follower_count"] == 12500

        analyzed = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/comment-demands",
            headers=headers,
            json={
                "platform": "douyin",
                "public_url": "https://www.douyin.com/video/73000123456789",
            },
        )
        assert analyzed.status_code == 200
        assert analyzed.json()["comment_count"] == 6
        assert {item["theme"] for item in analyzed.json()["themes"]} >= {
            "价格与购买",
            "教程与使用",
        }
        assert analyzed.json()["top_questions"]

        searched = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/trend-searches",
            headers=headers,
            json={"platform": "douyin", "keyword": "AI 工具"},
        )
        assert searched.status_code == 200
        assert searched.json()["keyword"] == "AI 工具"
        assert len(searched.json()["results"]) == 3
        search_history = client.get(
            f"/v1/workspaces/{workspace_id}/public-data/trend-searches"
        )
        assert search_history.status_code == 200
        assert search_history.json()[0]["id"] == searched.json()["id"]

        report = client.get(f"/v1/workspaces/{workspace_id}/public-data/daily-report")
        assert report.status_code == 200
        assert report.json()["monitored_accounts"] == 1
        assert report.json()["comment_analyses_24h"] == 1
        assert report.json()["alerts"][0]["kind"] == "competitor_viral"
        assert report.json()["actions"]


def test_competitor_requires_matching_public_profile_and_workspace() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, _ = _workspace_account_content(client)
        rejected = client.post(
            f"/v1/workspaces/{workspace_id}/public-data/competitors",
            headers={"X-CSRF-Token": csrf},
            json={
                "platform": "douyin",
                "name": "错误平台",
                "public_url": "https://www.xiaohongshu.com/user/profile/user-1",
            },
        )
        assert rejected.status_code == 422
        assert "平台不匹配" in rejected.json()["detail"]

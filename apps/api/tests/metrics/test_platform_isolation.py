from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.content.account_models import ColumnCampaign, ColumnCampaignKind
from app.modules.content.models import Content
from app.modules.metrics.benchmark import (
    BenchmarkInput,
    BenchmarkRange,
    BenchmarkRangeKind,
    calculate_benchmark,
)
from app.modules.metrics.benchmark_tasks import process_snapshot_confirmed_event
from app.modules.metrics.models import BenchmarkRun, MetricOutboxEvent
from app.modules.workspace.router import invite_attempts


@contextmanager
def configured_client() -> Iterator[tuple[TestClient, object]]:
    invite_attempts.clear()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
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


def create_account(client: TestClient, workspace_id: str, csrf: str, platform: str) -> dict:
    return client.post(
        f"/v1/workspaces/{workspace_id}/accounts",
        headers={"X-CSRF-Token": csrf},
        json={
            "platform": platform,
            "name": f"{platform} 账号",
            "objectives": ["reach"],
            "metric_weights": {"views": 1},
            "benchmark_sample_size": 30,
        },
    ).json()


def create_content_with_snapshot(
    client: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    account: dict,
    title: str,
    value: int,
    hours: int = 24,
    content_type: str = "video",
) -> tuple[dict, dict]:
    headers = {"X-CSRF-Token": csrf}
    content = client.post(
        "/v1/contents",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": account["platform"],
            "content_type": content_type,
            "title": title,
            "body": "仅使用合成测试数据",
        },
    ).json()
    content = client.patch(
        f"/v1/contents/{content['id']}",
        headers=headers,
        json={"status": "published"},
    ).json()
    collected_at = datetime.fromisoformat(content["published_at"]) + timedelta(hours=hours)
    snapshot = client.post(
        f"/v1/contents/{content['id']}/snapshots",
        headers=headers,
        json={
            "collected_at": collected_at.astimezone(UTC).isoformat(),
            "source": "manual",
            "metrics": [{"key": "views", "raw_value": value}],
        },
    ).json()
    confirmed = client.post(
        f"/v1/contents/{content['id']}/snapshots/{snapshot['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200
    return content, snapshot


def test_benchmark_filters_platform_account_maturity_and_column_and_persists_inputs() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "隔离工作区"}).json()
        login = client.post(
            "/v1/sessions/invite",
            json={"code": workspace["admin_code"], "display_name": "管理员"},
        ).json()
        workspace_id = workspace["workspace_id"]
        csrf = login["csrf_token"]
        douyin = create_account(client, workspace_id, csrf, "douyin")
        other_douyin = create_account(client, workspace_id, csrf, "douyin")
        xiaohongshu = create_account(client, workspace_id, csrf, "xiaohongshu")

        included, included_snapshot = create_content_with_snapshot(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=douyin,
            title="纳入样本",
            value=100,
        )
        excluded_by_column, excluded_by_column_snapshot = create_content_with_snapshot(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=douyin,
            title="另一栏目",
            value=200,
        )
        create_content_with_snapshot(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=douyin,
            title="成熟度不同",
            value=300,
            hours=72,
        )
        create_content_with_snapshot(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=xiaohongshu,
            title="平台不同",
            value=999,
        )
        create_content_with_snapshot(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=other_douyin,
            title="账号不同",
            value=888,
        )
        create_content_with_snapshot(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=douyin,
            title="内容类型不同",
            value=777,
            content_type="image_text",
        )

        other_workspace = client.post(
            "/v1/workspaces", json={"name": "另一工作区"}
        ).json()
        other_login = client.post(
            "/v1/sessions/invite",
            json={
                "code": other_workspace["admin_code"],
                "display_name": "另一管理员",
            },
        ).json()
        other_workspace_account = create_account(
            client,
            other_workspace["workspace_id"],
            other_login["csrf_token"],
            "douyin",
        )
        create_content_with_snapshot(
            client,
            workspace_id=other_workspace["workspace_id"],
            csrf=other_login["csrf_token"],
            account=other_workspace_account,
            title="工作区不同",
            value=666,
        )

        with Session(engine, expire_on_commit=False) as session:
            column = ColumnCampaign(
                workspace_id=UUID(workspace_id),
                account_id=UUID(douyin["id"]),
                name="目标栏目",
                kind=ColumnCampaignKind.COLUMN,
            )
            session.add(column)
            session.flush()
            session.get(Content, UUID(included["id"])).column_campaign_id = column.id  # type: ignore[union-attr]
            session.commit()

            unfiltered = calculate_benchmark(
                session,
                BenchmarkInput(
                    workspace_id=UUID(workspace_id),
                    platform="douyin",
                    account_id=UUID(douyin["id"]),
                    content_type="video",
                    maturity_bucket="24h",
                    range=BenchmarkRange(kind=BenchmarkRangeKind.ALL_HISTORY),
                    version="benchmark-v1",
                ),
            )
            assert unfiltered.sample_count == 2
            assert set(unfiltered.sample_snapshot_ids) == {
                UUID(included_snapshot["id"]),
                UUID(excluded_by_column_snapshot["id"]),
            }
            assert unfiltered.percentiles["views"].p90 == Decimal("190.0")

            result = calculate_benchmark(
                session,
                BenchmarkInput(
                    workspace_id=UUID(workspace_id),
                    platform="douyin",
                    account_id=UUID(douyin["id"]),
                    content_type="video",
                    maturity_bucket="24h",
                    range=BenchmarkRange(
                        kind=BenchmarkRangeKind.ALL_HISTORY,
                        column_campaign_id=column.id,
                    ),
                    version="benchmark-v1",
                ),
                weights={"views": Decimal("1")},
            )
            session.commit()

            assert result.sample_snapshot_ids == [UUID(included_snapshot["id"])]
            assert result.sample_count == 1
            assert result.percentiles["views"].median == Decimal("100")
            assert result.confidence.value == "raw_only"

            run = session.get(BenchmarkRun, result.run_id)
            assert run is not None
            assert run.sample_snapshot_ids == [included_snapshot["id"]]
            assert run.sample_count == 1
            assert run.range_settings["kind"] == "all_history"
            assert Decimal(run.percentile_values["views"]["p90"]) == Decimal("100")
            assert run.weights == {"views": "1"}
            assert run.algorithm_version == "benchmark-v1"

            assert session.get(Content, UUID(excluded_by_column["id"])) is not None

            event = session.scalar(
                select(MetricOutboxEvent).where(
                    MetricOutboxEvent.aggregate_id == UUID(included_snapshot["id"])
                )
            )
            assert event is not None
            task_run_id = process_snapshot_confirmed_event(session, event.id)
            assert task_run_id is not None
            task_run = session.get(BenchmarkRun, task_run_id)
            assert task_run is not None
            assert task_run.range_settings["latest_n"] == 30
            assert Decimal(task_run.weights["views"]) == Decimal("1")
            assert process_snapshot_confirmed_event(session, event.id) is None


def test_latest_n_and_date_ranges_are_deterministic_and_workspace_scoped() -> None:
    with configured_client() as (client, engine):
        workspace = client.post("/v1/workspaces", json={"name": "范围工作区"}).json()
        login = client.post(
            "/v1/sessions/invite",
            json={"code": workspace["admin_code"], "display_name": "管理员"},
        ).json()
        workspace_id = workspace["workspace_id"]
        csrf = login["csrf_token"]
        account = create_account(client, workspace_id, csrf, "douyin")
        first, _ = create_content_with_snapshot(
            client, workspace_id=workspace_id, csrf=csrf, account=account, title="第一条", value=10
        )
        second, second_snapshot = create_content_with_snapshot(
            client, workspace_id=workspace_id, csrf=csrf, account=account, title="第二条", value=20
        )

        with Session(engine) as session:
            latest = calculate_benchmark(
                session,
                BenchmarkInput(
                    workspace_id=UUID(workspace_id),
                    platform="douyin",
                    account_id=UUID(account["id"]),
                    content_type="video",
                    maturity_bucket="24h",
                    range={"kind": "latest_n", "latest_n": 1},
                    version="benchmark-v1",
                ),
            )
            assert latest.sample_snapshot_ids == [UUID(second_snapshot["id"])]

            start = datetime.fromisoformat(first["published_at"]) - timedelta(seconds=1)
            end = datetime.fromisoformat(second["published_at"]) + timedelta(seconds=1)
            ranged = calculate_benchmark(
                session,
                BenchmarkInput(
                    workspace_id=UUID(workspace_id),
                    platform="douyin",
                    account_id=UUID(account["id"]),
                    content_type="video",
                    maturity_bucket="24h",
                    range={"kind": "date_range", "start": start, "end": end},
                    version="benchmark-v1",
                ),
            )
            assert ranged.sample_count == 2

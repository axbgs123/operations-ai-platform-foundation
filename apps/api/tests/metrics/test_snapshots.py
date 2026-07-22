from collections.abc import Iterator
from contextlib import contextmanager
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_session
from app.main import app
from app.modules.metrics.models import MetricOutboxEvent, SnapshotMetricValue
from app.modules.workspace.router import invite_attempts


ROOT = Path(__file__).parents[4]


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


def create_published_content(
    client: TestClient,
    *,
    workspace_name: str = "快照工作区",
    platform: str = "douyin",
    content_type: str = "video",
) -> tuple[str, str, dict]:
    workspace = client.post("/v1/workspaces", json={"name": workspace_name}).json()
    workspace_id = workspace["workspace_id"]
    login = client.post(
        "/v1/sessions/invite",
        json={"code": workspace["admin_code"], "display_name": "管理员"},
    ).json()
    csrf = login["csrf_token"]
    headers = {"X-CSRF-Token": csrf}
    account = client.post(
        f"/v1/workspaces/{workspace_id}/accounts",
        headers=headers,
        json={
            "platform": platform,
            "name": f"{platform} 测试账号",
            "objectives": ["reach"],
            "metric_weights": {"views": 1},
            "benchmark_sample_size": 30,
        },
    ).json()
    content = client.post(
        "/v1/contents",
        headers=headers,
        json={
            "workspace_id": workspace_id,
            "account_id": account["id"],
            "platform": platform,
            "content_type": content_type,
            "title": "快照测试内容",
            "body": "仅使用合成测试数据",
        },
    ).json()
    published = client.patch(
        f"/v1/contents/{content['id']}",
        headers=headers,
        json={"status": "published"},
    ).json()
    return workspace_id, csrf, published


def collected_after(content: dict, **delta: int) -> str:
    published_at = datetime.fromisoformat(content["published_at"])
    return (published_at + timedelta(**delta)).astimezone(UTC).isoformat()


def test_snapshots_are_appended_and_never_overwrite_same_collection_time() -> None:
    with configured_client() as (client, _):
        _, csrf, content = create_published_content(client)
        headers = {"X-CSRF-Token": csrf}
        payload = {
            "collected_at": collected_after(content, hours=1),
            "source": "manual",
            "metrics": [{"key": "views", "raw_value": 100}],
        }

        first = client.post(
            f"/v1/contents/{content['id']}/snapshots", headers=headers, json=payload
        )
        second = client.post(
            f"/v1/contents/{content['id']}/snapshots", headers=headers, json=payload
        )
        listed = client.get(f"/v1/contents/{content['id']}/snapshots")

        assert first.status_code == second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
        assert len(listed.json()) == 2
        assert all(item["maturity_bucket"] == "1h" for item in listed.json())
        assert listed.json()[0]["completeness"]["ratio"] == 0.25


def test_snapshot_collected_before_publication_is_rejected() -> None:
    with configured_client() as (client, _):
        _, csrf, content = create_published_content(client)
        published_at = datetime.fromisoformat(content["published_at"])

        response = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": (published_at - timedelta(seconds=1)).isoformat(),
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 1}],
            },
        )

        assert response.status_code == 422
        assert "before publication" in response.json()["detail"]


def test_large_raw_counts_are_persisted_without_float_rounding() -> None:
    with configured_client() as (client, _):
        _, csrf, content = create_published_content(client)
        exact_count = 9_007_199_254_740_993

        response = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": collected_after(content, hours=1),
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": exact_count}],
            },
        )

        assert response.status_code == 201
        assert Decimal(str(response.json()["metrics"][0]["raw_value"])) == Decimal(
            exact_count
        )
        assert Decimal(
            str(response.json()["metrics"][0]["normalized_value"])
        ) == Decimal(exact_count)


def test_platform_and_content_type_incompatible_metric_is_rejected() -> None:
    with configured_client() as (client, _):
        _, csrf, content = create_published_content(
            client,
            platform="xiaohongshu",
            content_type="image_text",
        )

        response = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": csrf},
            json={
                "collected_at": collected_after(content, hours=24),
                "source": "manual",
                "metrics": [{"key": "average_watch_duration", "raw_value": 12}],
            },
        )

        assert response.status_code == 422
        assert "not compatible" in response.json()["detail"]


def test_confirmation_only_marks_valid_values_for_benchmark_and_writes_outbox() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, content = create_published_content(client)
        headers = {"X-CSRF-Token": csrf}
        created = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers=headers,
            json={
                "collected_at": collected_after(content, hours=25),
                "source": "screenshot",
                "metrics": [
                    {"key": "views", "raw_value": 100, "ocr_confidence": 0.4},
                    {"key": "likes", "raw_value": 12, "ocr_confidence": 0.95},
                    {"key": "comments", "raw_value": None, "ocr_confidence": 0.99},
                ],
            },
        )

        assert created.status_code == 201
        by_key = {item["key"]: item for item in created.json()["metrics"]}
        assert Decimal(by_key["views"]["raw_value"]) == Decimal(100)
        assert by_key["views"]["normalized_value"] is None
        assert Decimal(by_key["likes"]["normalized_value"]) == Decimal(12)
        assert not any(item["eligible_for_benchmark"] for item in by_key.values())

        confirmed = client.post(
            f"/v1/contents/{content['id']}/snapshots/{created.json()['id']}/confirm",
            headers=headers,
        )

        assert confirmed.status_code == 200
        confirmed_by_key = {
            item["key"]: item for item in confirmed.json()["metrics"]
        }
        assert confirmed_by_key["views"]["normalized_value"] is None
        assert confirmed_by_key["views"]["eligible_for_benchmark"] is False
        assert confirmed_by_key["likes"]["eligible_for_benchmark"] is True
        assert confirmed_by_key["comments"]["eligible_for_benchmark"] is False

        with Session(engine) as session:
            eligible = list(
                session.scalars(
                    select(SnapshotMetricValue).where(
                        SnapshotMetricValue.workspace_id == UUID(workspace_id),
                        SnapshotMetricValue.eligible_for_benchmark.is_(True),
                    )
                )
            )
            events = list(
                session.scalars(
                    select(MetricOutboxEvent).where(
                        MetricOutboxEvent.workspace_id == UUID(workspace_id)
                    )
                )
            )
        assert [value.metric_key for value in eligible] == ["likes"]
        assert len(events) == 1
        assert events[0].event_type == "metrics.snapshot_confirmed"


def test_confirm_is_idempotent_and_cross_workspace_snapshot_is_hidden() -> None:
    with configured_client() as (client, engine):
        _, first_csrf, content = create_published_content(client, workspace_name="甲工作区")
        created = client.post(
            f"/v1/contents/{content['id']}/snapshots",
            headers={"X-CSRF-Token": first_csrf},
            json={
                "collected_at": collected_after(content, hours=72),
                "source": "manual",
                "metrics": [{"key": "views", "raw_value": 300}],
            },
        ).json()
        first = client.post(
            f"/v1/contents/{content['id']}/snapshots/{created['id']}/confirm",
            headers={"X-CSRF-Token": first_csrf},
        )
        second = client.post(
            f"/v1/contents/{content['id']}/snapshots/{created['id']}/confirm",
            headers={"X-CSRF-Token": first_csrf},
        )

        assert first.status_code == second.status_code == 200
        with Session(engine) as session:
            assert len(list(session.scalars(select(MetricOutboxEvent)))) == 1

        _, other_csrf, _ = create_published_content(client, workspace_name="乙工作区")
        hidden = client.get(
            f"/v1/contents/{content['id']}/snapshots/{created['id']}",
            headers={"X-CSRF-Token": other_csrf},
        )
        assert hidden.status_code == 404


def test_migration_chain_creates_snapshot_value_and_outbox_tables() -> None:
    config = Config(str(ROOT / "apps" / "api" / "alembic.ini"))
    output = StringIO()

    with redirect_stdout(output):
        command.upgrade(config, "head", sql=True)

    sql = output.getvalue()
    assert "ALTER TABLE contents ADD COLUMN content_type" in sql
    assert "CREATE TABLE data_snapshots" in sql
    assert "CREATE TABLE snapshot_metric_values" in sql
    assert "CREATE TABLE metric_outbox_events" in sql

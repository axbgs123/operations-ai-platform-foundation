from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.content.models import Content
from app.modules.metrics.models import DataSnapshot, SnapshotMetricValue
from app.modules.metrics.snapshot_service import SnapshotService
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
    preview_manual,
)


def valid_row(index: int, **overrides: object) -> dict:
    row: dict[str, object] = {
        "platform_content_id": f"DY-{index}",
        "work_url": f"https://example.test/douyin/{index}",
        "title": f"合成确认标题 {index}",
        "body": "仅用于自动化测试",
        "published_at": "2026-07-20T10:00:00+08:00",
        "collected_at": "2026-07-21T10:00:00+08:00",
        "metrics": {"views": 100 + index, "likes": 10 + index},
    }
    row.update(overrides)
    return row


def test_confirm_writes_only_selected_valid_rows_and_is_idempotent() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        preview = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[valid_row(1), valid_row(2, title="")],
        )
        selected_ids = [row["id"] for row in preview["rows"]]

        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Content)) == 0
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 0

        first = client.post(
            f"/v1/imports/{preview['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"selected_row_ids": selected_ids},
        )

        assert first.status_code == 200, first.text
        result = first.json()
        assert len(result["content_ids"]) == 1
        assert len(result["snapshot_ids"]) == 1
        assert result["skipped_row_ids"] == [preview["rows"][1]["id"]]

        second = client.post(
            f"/v1/imports/{preview['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"selected_row_ids": selected_ids},
        )
        assert second.status_code == 200
        assert second.json() == result

        with Session(engine) as session:
            content = session.get(Content, UUID(result["content_ids"][0]))
            snapshot = session.get(DataSnapshot, UUID(result["snapshot_ids"][0]))
            assert content is not None and content.published_at is not None
            assert content.platform_content_id == "DY-1"
            assert snapshot is not None and snapshot.confirmed is True
            assert snapshot.source.value == "manual"
            assert session.scalar(select(func.count()).select_from(Content)) == 1
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 1


def test_manual_import_rejects_foreign_account_column_and_preserves_valid_column() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        other_account = client.post(
            f"/v1/workspaces/{workspace_id}/accounts",
            headers={"X-CSRF-Token": csrf},
            json={
                "platform": "douyin",
                "name": "另一个合成账号",
                "objectives": ["reach"],
                "metric_weights": {"views": 1},
                "benchmark_sample_size": 30,
            },
        ).json()
        column = client.post(
            (
                f"/v1/workspaces/{workspace_id}/accounts/"
                f"{other_account['id']}/columns-campaigns"
            ),
            headers={"X-CSRF-Token": csrf},
            json={"name": "其他账号栏目", "kind": "column"},
        ).json()

        rejected = client.post(
            f"/v1/workspaces/{workspace_id}/imports/manual/preview",
            headers={"X-CSRF-Token": csrf},
            json={
                "account_id": account["id"],
                "platform": "douyin",
                "content_type": "video",
                "rows": [
                    valid_row(30, column_campaign_id=column["id"]),
                ],
            },
        )
        assert rejected.status_code == 404

        own_column = client.post(
            (
                f"/v1/workspaces/{workspace_id}/accounts/"
                f"{account['id']}/columns-campaigns"
            ),
            headers={"X-CSRF-Token": csrf},
            json={"name": "当前账号栏目", "kind": "column"},
        ).json()
        preview = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[valid_row(31, column_campaign_id=own_column["id"])],
        )
        confirmed = client.post(
            f"/v1/imports/{preview['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"selected_row_ids": [preview["rows"][0]["id"]]},
        )
        assert confirmed.status_code == 200, confirmed.text
        with Session(engine) as session:
            content = session.get(
                Content,
                UUID(confirmed.json()["content_ids"][0]),
            )
            assert content is not None
            assert str(content.column_campaign_id) == own_column["id"]


def test_exact_duplicate_appends_snapshot_without_replacing_content() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        existing = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="保留原内容标题",
            work_url="https://example.test/douyin/9",
        )
        collected_at = datetime.fromisoformat(existing["published_at"]) + timedelta(
            hours=24
        )
        preview = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[
                valid_row(
                    9,
                    title="导入表里的新标题",
                    published_at=existing["published_at"],
                    collected_at=collected_at.isoformat(),
                )
            ],
        )
        assert preview["rows"][0]["status"] == "update"

        response = client.post(
            f"/v1/imports/{preview['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"selected_row_ids": [preview["rows"][0]["id"]]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["content_ids"] == [existing["id"]]
        with Session(engine) as session:
            content = session.get(Content, UUID(existing["id"]))
            assert content is not None and content.title == "保留原内容标题"
            assert session.scalar(select(func.count()).select_from(Content)) == 1
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 1
            assert session.scalar(
                select(func.count()).select_from(SnapshotMetricValue)
            ) == 2


def test_confirm_failure_rolls_back_every_formal_write(monkeypatch) -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        preview = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[valid_row(1), valid_row(2)],
        )
        original_create = SnapshotService.create
        calls = 0

        def fail_on_second_snapshot(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise ValueError("synthetic transaction failure")
            return original_create(self, *args, **kwargs)

        monkeypatch.setattr(SnapshotService, "create", fail_on_second_snapshot)
        response = client.post(
            f"/v1/imports/{preview['id']}/confirm",
            headers={"X-CSRF-Token": csrf},
            json={"selected_row_ids": [row["id"] for row in preview["rows"]]},
        )

        assert response.status_code == 422
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(Content)) == 0
            assert session.scalar(select(func.count()).select_from(DataSnapshot)) == 0

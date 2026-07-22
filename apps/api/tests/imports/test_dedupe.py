from datetime import datetime, timedelta

from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
    preview_manual,
)


def import_row(**overrides: object) -> dict:
    row: dict[str, object] = {
        "platform_content_id": "DY-EXACT",
        "work_url": "https://example.test/douyin/exact",
        "title": "合成去重标题",
        "body": "合成去重正文",
        "published_at": "2026-07-20T10:00:00+08:00",
        "collected_at": "2026-07-21T10:00:00+08:00",
        "metrics": {"views": 100},
    }
    row.update(overrides)
    return row


def test_exact_url_or_platform_id_is_update_only_within_platform_and_account() -> None:
    with configured_client() as (client, _):
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
        create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=other_account,
            title="其他账号同链接",
            work_url="https://example.test/douyin/exact",
        )

        isolated = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[import_row()],
        )
        assert isolated["rows"][0]["status"] == "new"

        existing = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="当前账号内容",
            work_url="https://example.test/douyin/exact",
        )
        matched = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[import_row(platform_content_id="DIFFERENT")],
        )

        assert matched["rows"][0]["status"] == "update"
        assert matched["rows"][0]["matched_content_id"] == existing["id"]


def test_title_and_publish_time_without_link_is_only_suspected_and_not_merged() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        existing = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="无链接相同标题",
            work_url=None,
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
                import_row(
                    platform_content_id=None,
                    work_url=None,
                    title=existing["title"],
                    published_at=existing["published_at"],
                    collected_at=collected_at.isoformat(),
                )
            ],
        )

        row = preview["rows"][0]
        assert row["errors"] == []
        assert row["status"] == "suspected_duplicate"
        assert row["matched_content_id"] == existing["id"]
        assert row["dedupe_reason"] == "same_title_and_published_at"


def test_duplicate_exact_keys_inside_one_batch_are_not_both_confirmable() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        preview = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[import_row(), import_row(title="同批次重复行")],
        )

        assert preview["rows"][0]["status"] == "new"
        assert preview["rows"][1]["status"] == "failed"
        assert preview["rows"][1]["errors"] == [
            {"field": "dedupe", "message": "duplicate exact key within import batch"}
        ]

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.content.account_models import Platform
from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.models import ExtensionToken
from app.modules.workspace.models import WorkspaceMember

from tests.imports.helpers import (
    configured_client,
    create_workspace_account,
    preview_manual,
)


FORBIDDEN_HISTORY_KEYS = {
    "authorization",
    "cookie",
    "header_mappings",
    "prompt",
    "raw_data",
    "recognition_output",
    "screenshot_bytes",
    "secret",
    "signed_url",
    "token",
}


def _keys(value: Any):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key.lower()
            yield from _keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _keys(nested)


def _row(index: int) -> dict[str, object]:
    return {
        "platform_content_id": f"history-{index}",
        "title": f"合成历史 {index}",
        "body": "只用于导入历史测试",
        "published_at": "2026-07-20T10:00:00+08:00",
        "collected_at": "2026-07-21T10:00:00+08:00",
        "metrics": {"views": 100 + index},
    }


def test_import_history_is_paginated_scoped_and_sanitized() -> None:
    with configured_client() as (client, _):
        workspace_id, csrf, account = create_workspace_account(client)
        first_batch = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[_row(1)],
        )
        second_batch = preview_manual(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account_id=account["id"],
            rows=[_row(2), {"title": ""}],
        )

        first = client.get(
            f"/v1/workspaces/{workspace_id}/imports/history",
            params={
                "platform": "douyin",
                "account_id": account["id"],
                "page": 1,
                "page_size": 1,
            },
        )
        assert first.status_code == 200, first.text
        payload = first.json()
        assert set(payload) == {
            "items",
            "page",
            "page_size",
            "total",
            "pages",
            "platform",
            "account_id",
        }
        assert payload["total"] == 2
        assert payload["page_size"] == 1
        assert payload["items"][0]["id"] == second_batch["id"]
        assert payload["items"][0]["method"] == "manual"
        assert payload["items"][0]["counts"] == {
            "new": 1,
            "update": 0,
            "suspected_duplicate": 0,
            "failed": 1,
        }
        assert payload["items"][0]["status"] == "waiting_confirmation"
        assert payload["items"][0]["next_action"] == "review"
        assert FORBIDDEN_HISTORY_KEYS.isdisjoint(set(_keys(payload)))
        assert "只用于导入历史测试" not in first.text
        viewer_code = client.post(
            f"/v1/workspaces/{workspace_id}/members/codes",
            headers={"X-CSRF-Token": csrf},
            json={"role": "viewer"},
        ).json()["code"]

        second = client.get(
            f"/v1/workspaces/{workspace_id}/imports/history",
            params={
                "platform": "douyin",
                "account_id": account["id"],
                "page": 2,
                "page_size": 1,
            },
        )
        assert second.status_code == 200
        assert second.json()["items"][0]["id"] == first_batch["id"]

        too_large = client.get(
            f"/v1/workspaces/{workspace_id}/imports/history",
            params={"page_size": 101},
        )
        assert too_large.status_code == 422

        foreign = client.post(
            "/v1/workspaces",
            json={"name": "其他导入工作区"},
        ).json()
        cross_workspace = client.get(
            f"/v1/workspaces/{foreign['workspace_id']}/imports/history"
        )
        assert cross_workspace.status_code == 404

        mismatch = client.get(
            f"/v1/workspaces/{workspace_id}/imports/history",
            params={
                "platform": "xiaohongshu",
                "account_id": account["id"],
            },
        )
        assert mismatch.status_code == 404

        viewer_login = client.post(
            "/v1/sessions/invite",
            json={"code": viewer_code, "display_name": "只读导入查看者"},
        )
        assert viewer_login.status_code == 201
        viewer_history = client.get(
            f"/v1/workspaces/{workspace_id}/imports/history",
            params={"platform": "douyin", "account_id": account["id"]},
        )
        assert viewer_history.status_code == 200
        viewer_preview = client.post(
            f"/v1/workspaces/{workspace_id}/imports/manual/preview",
            headers={"X-CSRF-Token": viewer_login.json()["csrf_token"]},
            json={
                "account_id": account["id"],
                "platform": "douyin",
                "content_type": "video",
                "rows": [_row(3)],
            },
        )
        assert viewer_preview.status_code == 403


def test_import_history_includes_extension_tasks_without_recognition_payload() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        now = datetime.now(UTC)
        with Session(engine) as session:
            member = session.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == UUID(workspace_id)
                )
            )
            assert member is not None
            token = ExtensionToken(
                workspace_id=member.workspace_id,
                member_id=member.id,
                token_hash="a" * 64,
                client_id="history-extension",
                exchange_fingerprint="b" * 64,
                scopes=["capture:create", "capture:upload", "capture:read"],
                issued_at=now,
                expires_at=now + timedelta(minutes=30),
            )
            session.add(token)
            session.flush()
            task = CaptureTask(
                workspace_id=member.workspace_id,
                token_id=token.id,
                member_id=member.id,
                platform=Platform.DOUYIN,
                page_version="fixture-v1",
                page_identifier="PRIVATE_PAGE_IDENTIFIER",
                collected_at=now,
                idempotency_key="history-extension-task",
                request_fingerprint="c" * 64,
                object_key="PRIVATE_OBJECT_KEY",
                review_url="/workspaces/synthetic/imports",
                expires_at=now + timedelta(hours=1),
                status=CaptureTaskStatus.SUCCEEDED,
                formal_snapshot_ids=[],
                recognition_output={
                    "ocr_text": "PRIVATE_OCR_BODY",
                    "metric_candidates": [],
                },
            )
            session.add(task)
            session.commit()
            task_id = str(task.id)

        response = client.get(
            f"/v1/workspaces/{workspace_id}/imports/history",
            params={"platform": "douyin"},
        )
        assert response.status_code == 200, response.text
        item = next(
            item for item in response.json()["items"] if item["id"] == task_id
        )
        assert item["method"] == "extension"
        assert item["account_id"] is None
        assert item["status"] == "waiting_confirmation"
        assert item["next_action"] == "review"
        assert "PRIVATE_" not in response.text

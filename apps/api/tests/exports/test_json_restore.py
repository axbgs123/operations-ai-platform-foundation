import json
from copy import deepcopy
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.modules.content.account_models import PlatformAccount
from app.modules.exports.json_backup import render_lightweight_json
from app.modules.exports.manifest import BackupFormatError, BackupManifest
from app.modules.exports.restore_preview import (
    RestoreAction,
    RestoreMode,
    apply_lightweight_restore,
    build_restore_preview,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.models.models import ModelConfig
from app.modules.risk_rag.models import RiskDocument
from app.modules.style_facts.fact_models import FactItem, FactSource
from app.modules.style_facts.style_models import AccountStyleProfile, StyleSample
from app.modules.workspace.models import (
    Workspace,
    WorkspaceAccessCode,
    WorkspaceMember,
    WorkspaceSession,
)
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)
from tests.exports.test_json_backup import _seed_portable_workspace


def _context(client, engine, workspace_id: str):
    token = client.cookies.get("session")
    assert token is not None
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert str(context.workspace_id) == workspace_id
        return context


def _login_role(
    admin: TestClient,
    *,
    workspace_id: str,
    csrf: str,
    role: str,
) -> TestClient:
    code = admin.post(
        f"/v1/workspaces/{workspace_id}/members/codes",
        headers={"X-CSRF-Token": csrf},
        json={"role": role},
    ).json()["code"]
    client = TestClient(app)
    response = client.post(
        "/v1/sessions/invite",
        json={"code": code, "display_name": f"合成{role}"},
    )
    assert response.status_code == 201
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


def _manifest_for(client, engine, workspace_id: str) -> BackupManifest:
    context = _context(client, engine, workspace_id)
    with Session(engine) as session:
        return BackupManifest.model_validate_json(
            render_lightweight_json(session, context)
        )


def test_preview_is_deterministic_and_classifies_create_skip_overwrite_conflict() -> None:
    with configured_client() as (source_client, engine):
        source_id, source_csrf, source_account = create_workspace_account(
            source_client,
            workspace_name="来源合成工作区",
        )
        create_published_content(
            source_client,
            workspace_id=source_id,
            csrf=source_csrf,
            account=source_account,
            title="预览动作合成内容",
            work_url=None,
        )
        manifest = _manifest_for(source_client, engine, source_id)
        source_context = _context(source_client, engine, source_id)
        with Session(engine) as session:
            same = build_restore_preview(
                session,
                source_context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="same-preview",
            )
            repeated = build_restore_preview(
                session,
                source_context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="same-preview",
            )
        assert same == repeated
        assert {item.action for item in same.items} == {RestoreAction.SKIP}

        changed_payload = manifest.model_dump(mode="json")
        account = next(
            record
            for record in changed_payload["records"]
            if record["record_type"] == "platform_account"
        )
        account["data"]["name"] = "允许覆盖的账号名称"
        changed = BackupManifest.model_validate(changed_payload)
        with Session(engine) as session:
            overwrite = build_restore_preview(
                session,
                source_context,
                changed,
                mode=RestoreMode.MERGE,
                idempotency_key="overwrite-preview",
            )
        account_item = next(
            item
            for item in overwrite.items
            if item.record_type == "platform_account"
        )
        assert account_item.action is RestoreAction.OVERWRITE
        assert not account_item.blocking

        conflicting_payload = deepcopy(changed_payload)
        content = next(
            record
            for record in conflicting_payload["records"]
            if record["record_type"] == "content"
        )
        content["platform"] = "xiaohongshu"
        conflicting = BackupManifest.model_validate(conflicting_payload)
        with Session(engine) as session:
            conflict = build_restore_preview(
                session,
                source_context,
                conflicting,
                mode=RestoreMode.MERGE,
                idempotency_key="conflict-preview",
            )
        content_item = next(
            item for item in conflict.items if item.record_type == "content"
        )
        assert content_item.action is RestoreAction.CONFLICT
        assert content_item.blocking

        new_workspace = source_client.post(
            "/v1/workspaces", json={"name": "新目标工作区"}
        ).json()
        target_client = TestClient(app)
        login = target_client.post(
            "/v1/sessions/invite",
            json={
                "code": new_workspace["admin_code"],
                "display_name": "目标管理员",
            },
        )
        assert login.status_code == 201
        target_context = _context(
            target_client,
            engine,
            new_workspace["workspace_id"],
        )
        with Session(engine) as session:
            create = build_restore_preview(
                session,
                target_context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="create-preview",
            )
        assert RestoreAction.CREATE in {item.action for item in create.items}
        assert all(
            item.action is RestoreAction.SKIP
            for item in create.items
            if item.record_type == "asset_reference"
        )
        target_client.close()


def test_preview_rejects_cross_platform_references_and_never_leaks_values() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="平台引用隔离测试",
            work_url=None,
        )
        manifest = _manifest_for(client, engine, workspace_id)
        payload = manifest.model_dump(mode="json")
        content = next(
            record
            for record in payload["records"]
            if record["record_type"] == "content"
        )
        content["data"]["body"] = "完整敏感文案不得进入预览"
        content["platform"] = "xiaohongshu"
        tampered = BackupManifest.model_validate(payload)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            preview = build_restore_preview(
                session,
                context,
                tampered,
                mode=RestoreMode.MERGE,
                idempotency_key="platform-conflict",
            )
        rendered = preview.model_dump_json()
        assert "完整敏感文案不得进入预览" not in rendered
        assert "conflict" in rendered
        assert "xiaohongshu" not in rendered


def test_preview_api_is_admin_only_idempotent_and_cross_workspace_hidden() -> None:
    with configured_client() as (admin, engine):
        workspace_id, csrf, _ = create_workspace_account(admin)
        manifest = _manifest_for(admin, engine, workspace_id)
        raw = manifest.model_dump_json().encode()
        editor = _login_role(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            role="editor",
        )
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "preview-api-1",
        }
        first = admin.post(
            f"/v1/workspaces/{workspace_id}/restore-previews?mode=merge",
            headers=headers,
            files={"file": ("backup.json", raw, "application/json")},
        )
        repeated = admin.post(
            f"/v1/workspaces/{workspace_id}/restore-previews?mode=merge",
            headers=headers,
            files={"file": ("backup.json", raw, "application/json")},
        )
        denied = editor.post(
            f"/v1/workspaces/{workspace_id}/restore-previews?mode=merge",
            headers={"Idempotency-Key": "editor-preview"},
            files={"file": ("backup.json", raw, "application/json")},
        )
        other = admin.post("/v1/workspaces", json={"name": "其他工作区"}).json()
        hidden = admin.post(
            f"/v1/workspaces/{other['workspace_id']}/restore-previews?mode=merge",
            headers=headers,
            files={"file": ("backup.json", raw, "application/json")},
        )

        assert first.status_code == repeated.status_code == 200
        assert first.json() == repeated.json()
        assert denied.status_code == 403
        assert hidden.status_code == 404
        editor.close()


def test_preview_has_no_writes_and_failure_injection_rolls_back_every_change() -> None:
    with configured_client() as (source_client, engine):
        source_id, _, _ = create_workspace_account(
            source_client,
            workspace_name="事务来源工作区",
        )
        manifest = _manifest_for(source_client, engine, source_id)
        target = source_client.post(
            "/v1/workspaces", json={"name": "事务目标工作区"}
        ).json()
        target_client = TestClient(app)
        login = target_client.post(
            "/v1/sessions/invite",
            json={
                "code": target["admin_code"],
                "display_name": "事务管理员",
            },
        )
        assert login.status_code == 201
        context = _context(target_client, engine, target["workspace_id"])

        with Session(engine) as session:
            before = session.scalar(
                select(func.count())
                .select_from(PlatformAccount)
                .where(PlatformAccount.workspace_id == context.workspace_id)
            )
            preview = build_restore_preview(
                session,
                context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="rollback-preview",
            )
            after_preview = session.scalar(
                select(func.count())
                .select_from(PlatformAccount)
                .where(PlatformAccount.workspace_id == context.workspace_id)
            )
            assert before == after_preview

            def fail_after_first_write(index: int, record_type: str) -> None:
                if index == 1:
                    raise RuntimeError("synthetic restore failure")

            with pytest.raises(RuntimeError, match="synthetic restore failure"):
                apply_lightweight_restore(
                    session,
                    context,
                    manifest,
                    preview,
                    failure_injector=fail_after_first_write,
                )
            session.rollback()

        with Session(engine) as session:
            after_failure = session.scalar(
                select(func.count())
                .select_from(PlatformAccount)
                .where(PlatformAccount.workspace_id == context.workspace_id)
            )
            assert after_failure == before
            assert session.get(Workspace, context.workspace_id) is not None
        target_client.close()


def test_successful_restore_is_retry_safe_and_backup_cannot_choose_target() -> None:
    with configured_client() as (source_client, engine):
        source_id, _, _ = create_workspace_account(source_client)
        manifest = _manifest_for(source_client, engine, source_id)
        target = source_client.post(
            "/v1/workspaces", json={"name": "幂等目标工作区"}
        ).json()
        target_client = TestClient(app)
        login = target_client.post(
            "/v1/sessions/invite",
            json={
                "code": target["admin_code"],
                "display_name": "幂等管理员",
            },
        )
        assert login.status_code == 201
        context = _context(target_client, engine, target["workspace_id"])
        with Session(engine) as session:
            preview = build_restore_preview(
                session,
                context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="restore-once",
            )
            apply_lightweight_restore(
                session,
                context,
                manifest,
                preview,
            )
            session.commit()
        with Session(engine) as session:
            retry_preview = build_restore_preview(
                session,
                context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="restore-retry",
            )
            assert {
                item.action
                for item in retry_preview.items
                if item.record_type != "asset_reference"
            } == {RestoreAction.SKIP}
            assert all(
                account.workspace_id == context.workspace_id
                for account in session.scalars(
                    select(PlatformAccount).where(
                        PlatformAccount.workspace_id == context.workspace_id
                    )
                )
            )
        target_client.close()


def test_new_workspace_restore_uses_server_target_without_inheriting_credentials() -> None:
    with configured_client() as (source_client, engine):
        source_id, _, _, _ = _seed_portable_workspace(source_client, engine)
        manifest = _manifest_for(source_client, engine, source_id)
        source_context = _context(source_client, engine, source_id)
        with Session(engine) as session:
            preview = build_restore_preview(
                session,
                source_context,
                manifest,
                mode=RestoreMode.NEW,
                idempotency_key="new-workspace-restore",
            )
            assert preview.target_workspace_id is not None
            assert preview.target_workspace_id != UUID(source_id)
            assert {
                item.action
                for item in preview.items
                if item.record_type != "asset_reference"
            } == {RestoreAction.CREATE}
            apply_lightweight_restore(
                session,
                source_context,
                manifest,
                preview,
            )
            session.commit()
            target_id = preview.target_workspace_id

        with Session(engine) as session:
            assert session.get(Workspace, target_id) is not None
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(WorkspaceMember)
                    .where(WorkspaceMember.workspace_id == target_id)
                )
                == 1
            )
            for model in (
                WorkspaceAccessCode,
                WorkspaceSession,
                ModelConfig,
            ):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.workspace_id == target_id)
                    )
                    == 0
                )
            for model in (
                AccountStyleProfile,
                StyleSample,
                FactSource,
                FactItem,
                RiskDocument,
            ):
                assert (
                    session.scalar(
                        select(func.count())
                        .select_from(model)
                        .where(model.workspace_id == target_id)
                    )
                    == 1
                )


def test_apply_rejects_manifest_changed_after_preview() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        manifest = _manifest_for(client, engine, workspace_id)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            preview = build_restore_preview(
                session,
                context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="immutable-preview",
            )
            changed_payload = manifest.model_dump(mode="json")
            account = next(
                record
                for record in changed_payload["records"]
                if record["record_type"] == "platform_account"
            )
            account["data"]["name"] = "预览后篡改名称"
            changed_manifest = BackupManifest.model_validate(changed_payload)
            with pytest.raises(ValueError, match="preview"):
                apply_lightweight_restore(
                    session,
                    context,
                    changed_manifest,
                    preview,
                )


def test_apply_rejects_target_state_changed_after_preview() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        manifest = _manifest_for(client, engine, workspace_id)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            preview = build_restore_preview(
                session,
                context,
                manifest,
                mode=RestoreMode.MERGE,
                idempotency_key="target-state-preview",
            )
            account = session.scalar(
                select(PlatformAccount).where(
                    PlatformAccount.workspace_id == context.workspace_id
                )
            )
            assert account is not None
            account.name = "预览后发生的并发修改"
            session.commit()
            with pytest.raises(ValueError, match="preview"):
                apply_lightweight_restore(
                    session,
                    context,
                    manifest,
                    preview,
                )


def test_restore_parser_rejects_untrusted_unknown_fields() -> None:
    payload = {
        "schema_version": "1.0.0",
        "product_version": "0.1.0",
        "exported_at": "2026-07-26T09:30:00Z",
        "workspace": {
            "source_id": "00000000-0000-4000-8000-000000000001",
            "name": "synthetic",
        },
        "records": [
            {
                "record_type": "platform_account",
                "source_id": "00000000-0000-4000-8000-000000000002",
                "platform": "douyin",
                "data": {
                    "name": "safe",
                    "token_hash": "must-not-be-accepted",
                },
            }
        ],
    }
    with pytest.raises((BackupFormatError, ValueError)):
        BackupManifest.model_validate_json(json.dumps(payload))

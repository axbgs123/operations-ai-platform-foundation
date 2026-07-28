import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import get_storage
from app.main import app
from app.modules.content.models import AssetCategory, ContentAsset
from app.modules.exports.manifest import (
    BACKUP_PRODUCT_VERSION,
    BACKUP_SCHEMA_VERSION,
    BackupFormatError,
    BackupManifest,
    parse_manifest_json,
)
from app.modules.exports.models import ExportTask
from app.modules.exports.router import get_export_enqueuer
from app.modules.exports.service import process_export_task
from app.modules.exports.json_backup import render_lightweight_json
from app.modules.metrics.models import (
    ContentType,
    MetricAggregation,
    MetricDefinition,
    MetricUnit,
)
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.content.account_models import Platform, PlatformAccount
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)
from app.modules.style_facts.fact_models import (
    FactConflictStatus,
    FactItem,
    FactItemStatus,
    FactSource,
    FactSourceKind,
    FactSourceLevel,
    FactSourceStatus,
)
from app.modules.style_facts.style_models import (
    AccountStyleProfile,
    StyleProfileStatus,
    StyleSample,
)
from app.modules.workspace.auth import InviteAuthService
from tests.exports.test_csv import MemoryExportStorage
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)


EXPORTED_AT = datetime(2026, 7, 26, 9, 30, tzinfo=UTC)


def _context(client, engine, workspace_id: str):
    token = client.cookies.get("session")
    assert token is not None
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert str(context.workspace_id) == workspace_id
        return context


def _seed_portable_workspace(client, engine):
    workspace_id, csrf, account = create_workspace_account(client)
    content = create_published_content(
        client,
        workspace_id=workspace_id,
        csrf=csrf,
        account=account,
        title="人工合成的可迁移内容",
        work_url="https://example.test/synthetic-content",
    )
    snapshot = client.post(
        f"/v1/contents/{content['id']}/snapshots",
        headers={"X-CSRF-Token": csrf},
        json={
            "collected_at": content["published_at"],
            "source": "manual",
            "metrics": [{"key": "views", "raw_value": 321}],
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    confirmed = client.post(
        f"/v1/contents/{content['id']}/snapshots/{snapshot.json()['id']}/confirm",
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200, confirmed.text
    with Session(engine) as session:
        session.add(
            ContentAsset(
                workspace_id=UUID(workspace_id),
                content_id=UUID(content["id"]),
                category=AssetCategory.COVER,
                object_key="private/source/object-key-must-not-leak",
                file_name="synthetic-cover.png",
                mime_type="image/png",
                size=1234,
            )
        )
        session.add(
            ModelConfig(
                workspace_id=UUID(workspace_id),
                provider="qianwen",
                model_id="qwen3.5-plus-2026-04-20",
                region="cn-beijing",
                provider_workspace_id=(
                    "llm-private-provider-workspace-must-not-leak"
                ),
                capabilities=["text"],
                status=ModelConfigStatus.EXPERIMENTAL,
                encrypted_api_key="encrypted-model-secret-must-not-leak",
            )
        )
        session.add(
            MetricDefinition(
                workspace_id=UUID(workspace_id),
                platform=Platform.DOUYIN,
                content_type=ContentType.VIDEO,
                key="synthetic_portable_metric",
                label="合成可迁移指标",
                unit=MetricUnit.COUNT,
                aggregation=MetricAggregation.LATEST,
                higher_is_better=True,
                is_default=False,
            )
        )
        style = AccountStyleProfile(
            workspace_id=UUID(workspace_id),
            account_id=UUID(account["id"]),
            scope_key="account",
            version=1,
            status=StyleProfileStatus.CONFIRMED,
            style={"tone": "synthetic-technical"},
            sample_content_ids=[content["id"]],
            diff={},
            column_campaign_id=None,
            base_profile_id=None,
            created_by=None,
            confirmed_by=None,
            confirmed_at=EXPORTED_AT,
        )
        session.add(style)
        session.add(
            StyleSample(
                workspace_id=UUID(workspace_id),
                account_id=UUID(account["id"]),
                scope_key="account",
                content_id=UUID(content["id"]),
                column_campaign_id=None,
                selected_by=None,
                selected_at=EXPORTED_AT,
            )
        )
        fact_source = FactSource(
            workspace_id=UUID(workspace_id),
            kind=FactSourceKind.TEXT,
            level=FactSourceLevel.L2,
            title="合成事实来源",
            status=FactSourceStatus.PARSED,
            source_text="FACT_SOURCE_PRIVATE_BODY_MUST_NOT_LEAK",
            raw_content=b"FACT_SOURCE_BINARY_MUST_NOT_LEAK",
            content_sha256="f" * 64,
        )
        session.add(fact_source)
        session.flush()
        session.add(
            FactItem(
                workspace_id=UUID(workspace_id),
                source_id=fact_source.id,
                field_name="产品名称",
                field_code="product_name",
                value="允许迁移的已确认合成事实",
                source_location="人工输入",
                confidence=1.0,
                status=FactItemStatus.CONFIRMED,
                conflict_status=FactConflictStatus.CLEAR,
                confirmed_by=None,
                confirmed_at=EXPORTED_AT,
                override_record=None,
            )
        )
        session.add(
            RiskDocument(
                workspace_id=UUID(workspace_id),
                platform=Platform.DOUYIN,
                scope=RiskDocumentScope.PRIVATE,
                source_level=RiskSourceLevel.S3,
                title="合成私有风控元数据",
                authorization_status=RiskAuthorizationStatus.AUTHORIZED,
                status=RiskDocumentStatus.ACTIVE,
                version=1,
                private_document_id="synthetic-risk-doc",
                effective_at=EXPORTED_AT,
                object_key="risk/private/object-key-must-not-leak",
                content_sha256="e" * 64,
                redistribution_authorized=False,
            )
        )
        session.commit()
    return workspace_id, csrf, account, content


def test_manifest_is_versioned_deterministic_and_excludes_secrets_and_bodies() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _, _ = _seed_portable_workspace(client, engine)
        other_client = type(client)(app=client.app)
        other_workspace_id, _, _ = create_workspace_account(
            other_client,
            workspace_name="不得导出的其他工作区",
        )
        with Session(engine) as session:
            other_account = session.scalar(
                select(PlatformAccount).where(
                    PlatformAccount.workspace_id == UUID(other_workspace_id)
                )
            )
            assert other_account is not None
            other_account.name = "CROSS_WORKSPACE_MARKER_MUST_NOT_LEAK"
            session.commit()
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            first = render_lightweight_json(
                session,
                context,
                exported_at=EXPORTED_AT,
            )
            second = render_lightweight_json(
                session,
                context,
                exported_at=EXPORTED_AT,
            )

        assert first == second
        manifest = BackupManifest.model_validate_json(first)
        assert manifest.schema_version == BACKUP_SCHEMA_VERSION
        assert manifest.product_version == BACKUP_PRODUCT_VERSION
        assert manifest.exported_at == EXPORTED_AT
        assert manifest.workspace.source_id == UUID(workspace_id)
        assert [record.record_type for record in manifest.records] == sorted(
            record.record_type for record in manifest.records
        )
        record_types = {record.record_type for record in manifest.records}
        assert {
            "platform_account",
            "objective_profile",
            "benchmark_profile",
            "metric_definition",
            "content",
            "asset_reference",
            "data_snapshot",
            "snapshot_metric_value",
            "style_profile",
            "style_sample",
            "fact_source_metadata",
            "fact_item",
            "risk_document_metadata",
        } <= record_types

        serialized = first.decode("utf-8")
        assert "CROSS_WORKSPACE_MARKER_MUST_NOT_LEAK" not in serialized
        for forbidden in (
            "encrypted_api_key",
            "encrypted-model-secret-must-not-leak",
            "provider_workspace_id",
            "llm-private-provider-workspace-must-not-leak",
            "code_hash",
            "token_hash",
            "csrf_hash",
            "claim_token",
            "lease_expires_at",
            "object_key",
            "private/source/object-key-must-not-leak",
            "raw_content",
            "source_text",
            "vector",
            "embedding",
            "download_url",
            '"authorization":',
            "bearer ",
            "cookie",
            "base64",
            "FACT_SOURCE_PRIVATE_BODY_MUST_NOT_LEAK",
            "FACT_SOURCE_BINARY_MUST_NOT_LEAK",
            "risk/private/object-key-must-not-leak",
        ):
            assert forbidden.lower() not in serialized.lower()
        assert "允许迁移的已确认合成事实" in serialized
        other_client.close()


def test_manifest_requires_supported_version_timezone_and_strict_fields() -> None:
    valid = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "product_version": BACKUP_PRODUCT_VERSION,
        "exported_at": "2026-07-26T17:30:00+08:00",
        "workspace": {
            "source_id": "00000000-0000-4000-8000-000000000001",
            "name": "合成备份",
        },
        "records": [],
    }
    parsed = parse_manifest_json(
        json.dumps(valid, ensure_ascii=False).encode("utf-8")
    )
    assert parsed.exported_at.utcoffset() is not None

    for field, value in (
        ("schema_version", "latest"),
        ("schema_version", "99.0.0"),
        ("exported_at", "2026-07-26T09:30:00"),
    ):
        invalid = {**valid, field: value}
        with pytest.raises((BackupFormatError, ValidationError)):
            parse_manifest_json(
                json.dumps(invalid, ensure_ascii=False).encode("utf-8")
            )

    with pytest.raises((BackupFormatError, ValidationError)):
        parse_manifest_json(
            json.dumps(
                {**valid, "encrypted_api_key": "must-reject-extra"},
                ensure_ascii=False,
            ).encode("utf-8")
        )


def test_parser_rejects_duplicate_keys_oversized_or_broken_references() -> None:
    duplicate = (
        b'{"schema_version":"1.0.0","schema_version":"1.0.0",'
        b'"product_version":"0.1.0","exported_at":"2026-07-26T09:30:00Z",'
        b'"workspace":{"source_id":"00000000-0000-4000-8000-000000000001",'
        b'"name":"synthetic"},"records":[]}'
    )
    with pytest.raises(BackupFormatError, match="duplicate"):
        parse_manifest_json(duplicate)

    with pytest.raises(BackupFormatError, match="size"):
        parse_manifest_json(b"{}" + b" " * (2_000_001))

    broken = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "product_version": BACKUP_PRODUCT_VERSION,
        "exported_at": "2026-07-26T09:30:00Z",
        "workspace": {
            "source_id": "00000000-0000-4000-8000-000000000001",
            "name": "synthetic",
        },
        "records": [
            {
                "record_type": "content",
                "source_id": "00000000-0000-4000-8000-000000000010",
                "platform": "douyin",
                "data": {
                    "account_id": "00000000-0000-4000-8000-000000000099",
                    "objective_profile_id": "00000000-0000-4000-8000-000000000098",
                    "benchmark_profile_id": "00000000-0000-4000-8000-000000000097",
                    "content_type": "video",
                    "title": "broken",
                    "body": "",
                    "status": "draft",
                },
            }
        ],
    }
    with pytest.raises(BackupFormatError, match="reference"):
        parse_manifest_json(
            json.dumps(broken, ensure_ascii=False).encode("utf-8")
        )


def test_record_schema_rejects_wrong_field_types_instead_of_coercing() -> None:
    invalid = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "product_version": BACKUP_PRODUCT_VERSION,
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
                "data": {"name": 123},
            }
        ],
    }
    with pytest.raises(BackupFormatError):
        parse_manifest_json(
            json.dumps(invalid, ensure_ascii=False).encode("utf-8")
        )


def test_json_backup_reuses_async_idempotent_export_and_object_storage() -> None:
    storage = MemoryExportStorage()
    queued: list[UUID] = []
    with configured_client() as (client, engine):
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        app.dependency_overrides[get_storage] = lambda: storage
        workspace_id, csrf, _, _ = _seed_portable_workspace(client, engine)
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "json-backup-1",
        }
        first = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "json"},
        )
        repeated = client.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "json"},
        )

        assert first.status_code == repeated.status_code == 202
        assert first.json()["id"] == repeated.json()["id"]
        task_id = UUID(first.json()["id"])
        assert queued == [task_id]
        with Session(engine) as session:
            process_export_task(session, task_id, storage)
        task = None
        with Session(engine) as session:
            task = session.scalar(select(ExportTask).where(ExportTask.id == task_id))
            assert task is not None
            assert task.file_name is not None
            assert task.file_name.endswith(".json")
            assert task.mime_type == "application/json"
            assert task.object_key is not None
        payload = next(iter(storage.objects.values()))[0]
        assert BackupManifest.model_validate_json(payload)

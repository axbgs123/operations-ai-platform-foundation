from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.core.security import WorkspaceContext
from app.core.storage import StoredObject, get_storage
from app.main import app
from app.modules.content.models import ContentAsset
from app.modules.content.account_models import Platform
from app.modules.exports.models import (
    FullRestorePhase,
    FullRestoreStatus,
    KnowledgeIndexRebuild,
    KnowledgeIndexStatus,
    RestoreJob,
)
from app.modules.exports.restore_preview import RestoreMode
from app.modules.exports.router import get_restore_enqueuer
from app.modules.exports.zip_backup import build_full_backup_zip
from app.modules.exports.zip_restore import (
    FullRestoreIdempotencyConflict,
    confirm_full_restore,
    create_full_restore_preview,
    process_full_restore_task,
)
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.models.catalog import (
    QIANWEN_EMBEDDING_CONTRACT_VERSION,
    QIANWEN_EMBEDDING_DIMENSION,
    QIANWEN_EMBEDDING_MODEL_ID,
)
from app.modules.risk_rag.models import (
    RiskAuthorizationStatus,
    RiskChunkEmbedding,
    RiskDocument,
    RiskDocumentScope,
    RiskDocumentStatus,
    RiskSourceLevel,
)
from app.modules.risk_rag.indexing import (
    ConfiguredMockRiskEmbedder,
    RiskIndexRebuildCoordinator,
)
from app.modules.workspace.auth import InviteAuthService
from app.modules.workspace.models import (
    Workspace,
    WorkspaceAccessCode,
    WorkspaceSession,
)
from tests.exports.test_csv import _login_role
from tests.exports.test_json_backup import _seed_portable_workspace
from tests.imports.helpers import configured_client, create_workspace_account


NOW = datetime(2026, 7, 26, 13, 0, tzinfo=UTC)


class MemoryRestoreStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None:
        self.objects[object_key] = (content, mime_type)

    def get_object(self, object_key: str) -> bytes:
        try:
            return self.objects[object_key][0]
        except KeyError as error:
            raise FileNotFoundError(object_key) from error

    def delete_object(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def inspect_object(self, object_key: str) -> StoredObject | None:
        stored = self.objects.get(object_key)
        if stored is None:
            return None
        return StoredObject(size=len(stored[0]), mime_type=stored[1])


def _context(client, engine, workspace_id: str):
    token = client.cookies.get("session")
    assert token is not None
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert context.workspace_id == UUID(workspace_id)
        return context


def _source_archive(
    client,
    engine,
    storage: MemoryRestoreStorage,
    *,
    include_xiaohongshu: bool = False,
):
    workspace_id, csrf, _, _ = _seed_portable_workspace(client, engine)
    with Session(engine) as session:
        asset = session.scalar(
            select(ContentAsset).where(
                ContentAsset.workspace_id == UUID(workspace_id)
            )
        )
        document = session.scalar(
            select(RiskDocument).where(
                RiskDocument.workspace_id == UUID(workspace_id)
            )
        )
        assert asset is not None
        assert document is not None
        asset.object_key = f"workspaces/{workspace_id}/source/cover.png"
        document.object_key = f"workspaces/{workspace_id}/source/risk.txt"
        document.file_name = "risk.txt"
        document.mime_type = "text/plain"
        document.redistribution_authorized = True
        if include_xiaohongshu:
            xhs = RiskDocument(
                workspace_id=UUID(workspace_id),
                platform=Platform.XIAOHONGSHU,
                scope=RiskDocumentScope.PRIVATE,
                source_level=RiskSourceLevel.S3,
                title="合成小红书私有知识",
                authorization_status=RiskAuthorizationStatus.AUTHORIZED,
                status=RiskDocumentStatus.ACTIVE,
                version=1,
                private_document_id="synthetic-xhs-risk-doc",
                effective_at=NOW,
                file_name="xhs-risk.txt",
                mime_type="text/plain",
                object_key=f"workspaces/{workspace_id}/source/xhs-risk.txt",
                redistribution_authorized=True,
            )
            session.add(xhs)
        session.commit()
    storage.put_object(
        f"workspaces/{workspace_id}/source/cover.png",
        b"synthetic-cover",
        mime_type="image/png",
    )
    storage.put_object(
        f"workspaces/{workspace_id}/source/risk.txt",
        b"synthetic risk knowledge",
        mime_type="text/plain",
    )
    if include_xiaohongshu:
        storage.put_object(
            f"workspaces/{workspace_id}/source/xhs-risk.txt",
            b"synthetic xiaohongshu risk knowledge",
            mime_type="text/plain",
        )
    context = _context(client, engine, workspace_id)
    with Session(engine) as session:
        payload = build_full_backup_zip(
            session,
            context,
            storage,
            exported_at=NOW,
        )
    return workspace_id, csrf, payload


def test_full_restore_preview_is_idempotent_staged_and_has_no_business_writes() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, storage)
        target_id, _, _ = create_workspace_account(
            source,
            workspace_name="完整恢复目标",
        )
        context = _context(source, engine, target_id)
        with Session(engine, expire_on_commit=False) as session:
            before = session.scalar(
                select(func.count())
                .select_from(ContentAsset)
                .where(ContentAsset.workspace_id == context.workspace_id)
            )
            job, created = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="full-preview-1",
            )
            repeated, repeated_created = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="full-preview-1",
            )
            session.commit()
            after = session.scalar(
                select(func.count())
                .select_from(ContentAsset)
                .where(ContentAsset.workspace_id == context.workspace_id)
            )
        assert created
        assert not repeated_created
        assert repeated.id == job.id
        assert job.status is FullRestoreStatus.QUEUED
        assert job.phase is FullRestorePhase.PREVIEW_READY
        assert job.preview_id
        assert job.manifest_fingerprint
        assert before == after == 0
        staged = [
            key
            for key in storage.objects
            if f"/restore-staging/{job.id}/" in key
        ]
        assert staged
        assert all(key.startswith(f"workspaces/{target_id}/") for key in staged)
        assert "synthetic risk knowledge" not in str(job.preview_json)

        with Session(engine) as session:
            with pytest.raises(FullRestoreIdempotencyConflict):
                create_full_restore_preview(
                    session,
                    context,
                    payload + b"changed",
                    storage,
                    mode=RestoreMode.MERGE,
                    idempotency_key="full-preview-1",
                )


def test_object_move_failure_compensates_database_and_partial_objects() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, storage)
        target_id, _, _ = create_workspace_account(
            source,
            workspace_name="补偿目标",
        )
        context = _context(source, engine, target_id)
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="compensation-preview",
            )
            session.commit()
            job_id = job.id
            preview_id = job.preview_id
            fingerprint = job.manifest_fingerprint

        def fail_second_move(phase: str, index: int) -> None:
            if phase == "move_object" and index == 2:
                raise RuntimeError("synthetic object move failure")

        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="synthetic object move"):
                confirm_full_restore(
                    session,
                    context,
                    job_id,
                    preview_id=preview_id,
                    manifest_fingerprint=fingerprint,
                    idempotency_key="confirm-compensation",
                    storage=storage,
                    failure_injector=fail_second_move,
                )
        with Session(engine) as session:
            failed = session.get(RestoreJob, job_id)
            assert failed is not None
            assert failed.status is FullRestoreStatus.FAILED
            assert failed.phase is FullRestorePhase.FAILED
            assert failed.error_code == "RESTORE_OBJECT_MOVE_FAILED"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ContentAsset)
                    .where(ContentAsset.workspace_id == UUID(target_id))
                )
                == 0
            )
        final_prefix = f"workspaces/{target_id}/restored/"
        assert not any(key.startswith(final_prefix) for key in storage.objects)
        assert any(
            f"/restore-staging/{job_id}/" in key for key in storage.objects
        )


def test_successful_restore_is_idempotent_and_rebuilds_mock_embeddings() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(
            source,
            engine,
            storage,
            include_xiaohongshu=True,
        )
        target_id, _, _ = create_workspace_account(
            source,
            workspace_name="成功恢复目标",
        )
        context = _context(source, engine, target_id)
        with Session(engine) as session:
            session.add(
                ModelConfig(
                    workspace_id=UUID(target_id),
                    provider="mock",
                    model_id="mock-v1",
                    capabilities=["embedding"],
                    status=ModelConfigStatus.VERIFIED,
                    encrypted_api_key="synthetic-encrypted-key",
                )
            )
            session.commit()
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="success-preview",
            )
            session.commit()
            job_id = job.id
            preview_id = job.preview_id
            fingerprint = job.manifest_fingerprint
        with Session(engine) as session:
            completed = confirm_full_restore(
                session,
                context,
                job_id,
                preview_id=preview_id,
                manifest_fingerprint=fingerprint,
                idempotency_key="success-confirm",
                storage=storage,
            )
            repeated = confirm_full_restore(
                session,
                context,
                job_id,
                preview_id=preview_id,
                manifest_fingerprint=fingerprint,
                idempotency_key="success-confirm",
                storage=storage,
            )
            assert completed.id == repeated.id
            assert completed.status is FullRestoreStatus.SUCCEEDED
            assert completed.phase is FullRestorePhase.COMPLETED
            assert completed.knowledge_index_message == "知识索引重建中"
            rebuilds = list(
                session.scalars(
                    select(KnowledgeIndexRebuild).where(
                        KnowledgeIndexRebuild.restore_job_id == job_id
                    )
                )
            )
            assert {item.platform.value for item in rebuilds} == {
                "douyin",
                "xiaohongshu",
            }
            assert all(
                item.status is KnowledgeIndexStatus.QUEUED
                for item in rebuilds
            )
            assert {item.model_id for item in rebuilds} == {"mock-v1"}
            assert {item.embedding_version for item in rebuilds} == {
                "mock-risk-embedding-v1"
            }
            assert {item.dimension for item in rebuilds} == {4}
            config_id = rebuilds[0].model_config_id
            assert config_id is not None
        factory = sessionmaker(engine, expire_on_commit=False)
        coordinator = RiskIndexRebuildCoordinator(
            factory,
            context=WorkspaceContext(
                workspace_id=UUID(target_id),
                member_id=context.member_id,
                role="admin",
            ),
        )
        for rebuild in rebuilds:
            coordinator.run(
                rebuild.id,
                embedder=ConfiguredMockRiskEmbedder(
                    config_id, model_id="mock-v1"
                ),
            )
        with Session(engine) as session:
            refreshed = list(
                session.scalars(
                    select(KnowledgeIndexRebuild).where(
                        KnowledgeIndexRebuild.restore_job_id == job_id
                    )
                )
            )
            assert all(
                item.status is KnowledgeIndexStatus.SUCCEEDED
                for item in refreshed
            )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RiskChunkEmbedding)
                    .where(RiskChunkEmbedding.workspace_id == UUID(target_id))
                )
                > 0
            )


def test_new_workspace_restore_does_not_inherit_credentials_and_degrades_index() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        source_id, _, payload = _source_archive(source, engine, storage)
        context = _context(source, engine, source_id)
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.NEW,
                idempotency_key="new-preview",
            )
            session.commit()
            target_id = job.target_workspace_id
            assert target_id is not None
            completed = confirm_full_restore(
                session,
                context,
                job.id,
                preview_id=job.preview_id,
                manifest_fingerprint=job.manifest_fingerprint,
                idempotency_key="new-confirm",
                storage=storage,
            )
            assert completed.status is FullRestoreStatus.SUCCEEDED
            assert completed.knowledge_index_message == "知识索引重建中"
            rebuild = session.scalar(
                select(KnowledgeIndexRebuild).where(
                    KnowledgeIndexRebuild.restore_job_id == job.id
                )
            )
            assert rebuild is not None
            assert rebuild.status is KnowledgeIndexStatus.CONFIGURATION_REQUIRED
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
            assert session.get(Workspace, target_id) is not None


def test_qianwen_restore_only_queues_rebuild_after_restore_commit() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, storage)
        target_id, _, _ = create_workspace_account(
            source,
            workspace_name="千问异步重建目标",
        )
        context = _context(source, engine, target_id)
        with Session(engine) as session:
            session.add(
                ModelConfig(
                    workspace_id=UUID(target_id),
                    provider="qianwen",
                    model_id=QIANWEN_EMBEDDING_MODEL_ID,
                    capabilities=["embedding"],
                    status=ModelConfigStatus.EXPERIMENTAL,
                    encrypted_api_key="encrypted-synthetic-never-decrypted",
                    region="cn-beijing",
                    provider_workspace_id="llm-abcd1234",
                    encryption_key_version="v1",
                )
            )
            session.commit()
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="qianwen-preview",
            )
            session.commit()
            completed = confirm_full_restore(
                session,
                context,
                job.id,
                preview_id=job.preview_id,
                manifest_fingerprint=job.manifest_fingerprint,
                idempotency_key="qianwen-confirm",
                storage=storage,
            )
            rebuild = session.scalar(
                select(KnowledgeIndexRebuild).where(
                    KnowledgeIndexRebuild.restore_job_id == job.id
                )
            )
            assert completed.status is FullRestoreStatus.SUCCEEDED
            assert rebuild is not None
            assert rebuild.status is KnowledgeIndexStatus.QUEUED
            assert rebuild.provider == "qianwen"
            assert rebuild.model_id == QIANWEN_EMBEDDING_MODEL_ID
            assert (
                rebuild.contract_version
                == QIANWEN_EMBEDDING_CONTRACT_VERSION
            )
            assert rebuild.dimension == QIANWEN_EMBEDDING_DIMENSION
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RiskChunkEmbedding)
                    .where(
                        RiskChunkEmbedding.workspace_id == UUID(target_id)
                    )
                )
                == 0
            )


def test_restore_rejects_stale_preview_permission_change_and_cross_workspace() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, storage)
        target_id, _, _ = create_workspace_account(source)
        context = _context(source, engine, target_id)
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="stale-preview",
            )
            session.commit()
            with pytest.raises(ValueError, match="stale"):
                confirm_full_restore(
                    session,
                    context,
                    job.id,
                    preview_id="different-preview",
                    manifest_fingerprint=job.manifest_fingerprint,
                    idempotency_key="stale-confirm",
                    storage=storage,
                )
            other_id, _, _ = create_workspace_account(source)
            other_context = _context(source, engine, other_id)
            with pytest.raises(LookupError):
                confirm_full_restore(
                    session,
                    other_context,
                    job.id,
                    preview_id=job.preview_id,
                    manifest_fingerprint=job.manifest_fingerprint,
                    idempotency_key="cross-workspace-confirm",
                    storage=storage,
                )


def test_full_restore_api_is_admin_only_async_and_workspace_scoped() -> None:
    storage = MemoryRestoreStorage()
    queued: list[UUID] = []
    with configured_client() as (admin, engine):
        app.dependency_overrides[get_storage] = lambda: storage
        app.dependency_overrides[get_restore_enqueuer] = lambda: queued.append
        workspace_id, csrf, payload = _source_archive(admin, engine, storage)
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "api-zip-preview",
        }
        created = admin.post(
            f"/v1/workspaces/{workspace_id}/zip-restores?mode=merge",
            headers=headers,
            files={"file": ("backup.zip", payload, "application/zip")},
        )
        assert created.status_code == 202, created.text
        body = created.json()
        assert body["status"] == "queued"
        assert body["phase"] == "preview_ready"
        assert body["preview_id"]
        assert "synthetic risk knowledge" not in created.text

        editor = _login_role(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            role="editor",
        )
        denied = editor.post(
            f"/v1/workspaces/{workspace_id}/zip-restores?mode=merge",
            headers={"Idempotency-Key": "editor-zip-preview"},
            files={"file": ("backup.zip", payload, "application/zip")},
        )
        assert denied.status_code == 403

        confirmation = admin.post(
            (
                f"/v1/workspaces/{workspace_id}/zip-restores/"
                f"{body['id']}/confirm"
            ),
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "api-zip-confirm",
            },
            json={
                "preview_id": body["preview_id"],
                "manifest_fingerprint": body["manifest_fingerprint"],
            },
        )
        assert confirmation.status_code == 202, confirmation.text
        assert queued == [UUID(body["id"])]

        status = admin.get(
            f"/v1/workspaces/{workspace_id}/zip-restores/{body['id']}"
        )
        assert status.status_code == 200
        other = admin.post(
            "/v1/workspaces",
            json={"name": "API跨工作区目标"},
        ).json()
        hidden = admin.get(
            (
                f"/v1/workspaces/{other['workspace_id']}/zip-restores/"
                f"{body['id']}"
            )
        )
        assert hidden.status_code == 404
        editor.close()


def test_staging_or_database_failure_never_leaves_partial_business_state() -> None:
    class FailingStagingStorage(MemoryRestoreStorage):
        def put_object(
            self,
            object_key: str,
            content: bytes,
            *,
            mime_type: str,
        ) -> None:
            if "/restore-staging/" in object_key and "/files/" in object_key:
                raise RuntimeError("synthetic staging failure")
            super().put_object(
                object_key,
                content,
                mime_type=mime_type,
            )

    source_storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, source_storage)
        target_id, _, _ = create_workspace_account(source)
        context = _context(source, engine, target_id)
        failing = FailingStagingStorage()
        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="staging"):
                create_full_restore_preview(
                    session,
                    context,
                    payload,
                    failing,
                    mode=RestoreMode.MERGE,
                    idempotency_key="staging-failure",
                )
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(RestoreJob)
                    .where(RestoreJob.workspace_id == UUID(target_id))
                )
                == 0
            )
        assert not any(
            "/restore-staging/" in key for key in failing.objects
        )

        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                source_storage,
                mode=RestoreMode.MERGE,
                idempotency_key="database-failure",
            )
            session.commit()
            job_id = job.id

        def fail_database(phase: str, index: int) -> None:
            if phase == "database_write" and index == 1:
                raise RuntimeError("synthetic database failure")

        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="database"):
                confirm_full_restore(
                    session,
                    context,
                    job_id,
                    preview_id=job.preview_id,
                    manifest_fingerprint=job.manifest_fingerprint,
                    idempotency_key="database-failure-confirm",
                    storage=source_storage,
                    failure_injector=fail_database,
                )
        with Session(engine) as session:
            failed = session.get(RestoreJob, job_id)
            assert failed is not None
            assert failed.error_code == "RESTORE_DATABASE_FAILED"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ContentAsset)
                    .where(ContentAsset.workspace_id == UUID(target_id))
                )
                == 0
            )


def test_compensation_failure_is_diagnostic_and_archive_tampering_is_stale() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, storage)
        target_id, _, _ = create_workspace_account(source)
        context = _context(source, engine, target_id)
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="compensation-required",
            )
            session.commit()
            job_id = job.id
            archive_key = job.archive_object_key

        original_archive = storage.objects[archive_key]
        storage.objects[archive_key] = (payload + b"tampered", "application/zip")
        with Session(engine) as session:
            with pytest.raises(ValueError, match="stale"):
                confirm_full_restore(
                    session,
                    context,
                    job_id,
                    preview_id=job.preview_id,
                    manifest_fingerprint=job.manifest_fingerprint,
                    idempotency_key="tampered-confirm",
                    storage=storage,
                )
        storage.objects[archive_key] = original_archive

        def fail_move_and_compensation(phase: str, index: int) -> None:
            if phase == "move_object" and index == 2:
                raise RuntimeError("synthetic move failure")
            if phase == "compensate_database" and index == 1:
                raise RuntimeError("synthetic compensation failure")

        with Session(engine) as session:
            with pytest.raises(RuntimeError, match="move"):
                confirm_full_restore(
                    session,
                    context,
                    job_id,
                    preview_id=job.preview_id,
                    manifest_fingerprint=job.manifest_fingerprint,
                    idempotency_key="compensation-confirm",
                    storage=storage,
                    failure_injector=fail_move_and_compensation,
                )
        with Session(engine) as session:
            failed = session.get(RestoreJob, job_id)
            assert failed is not None
            assert failed.phase is FullRestorePhase.COMPENSATION_REQUIRED
            assert failed.error_code == "RESTORE_COMPENSATION_REQUIRED"


def test_restore_worker_losing_claim_cannot_publish_old_result() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        _, _, payload = _source_archive(source, engine, storage)
        target_id, _, _ = create_workspace_account(source)
        context = _context(source, engine, target_id)
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="claim-preview",
            )
            job.confirm_idempotency_key = "claim-confirm"
            session.commit()
            job_id = job.id

        class ClaimTakeoverStorage(MemoryRestoreStorage):
            def __init__(self) -> None:
                self.objects = storage.objects
                self.taken = False

            def put_object(
                self,
                object_key: str,
                content: bytes,
                *,
                mime_type: str,
            ) -> None:
                super().put_object(
                    object_key,
                    content,
                    mime_type=mime_type,
                )
                if "/restored/" in object_key and not self.taken:
                    self.taken = True
                    with Session(engine) as takeover:
                        takeover.execute(
                            update(RestoreJob)
                            .where(RestoreJob.id == job_id)
                            .values(claim_token="replacement-worker")
                        )
                        takeover.commit()

        takeover_storage = ClaimTakeoverStorage()
        with Session(engine) as session:
            process_full_restore_task(session, job_id, takeover_storage)
        with Session(engine) as session:
            current = session.get(RestoreJob, job_id)
            assert current is not None
            assert current.status is not FullRestoreStatus.SUCCEEDED
            assert current.claim_token == "replacement-worker"
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(ContentAsset)
                    .where(ContentAsset.workspace_id == UUID(target_id))
                )
                == 0
            )
        assert not any(
            key.startswith(f"workspaces/{target_id}/restored/")
            for key in takeover_storage.objects
        )


def test_merge_back_into_source_skips_existing_files_without_rewriting() -> None:
    storage = MemoryRestoreStorage()
    with configured_client() as (source, engine):
        workspace_id, _, payload = _source_archive(source, engine, storage)
        context = _context(source, engine, workspace_id)
        with Session(engine) as session:
            before_assets = list(
                session.scalars(
                    select(ContentAsset).where(
                        ContentAsset.workspace_id == UUID(workspace_id)
                    )
                )
            )
            before_asset_keys = {asset.object_key for asset in before_assets}
            before_risk_key = session.scalar(
                select(RiskDocument.object_key).where(
                    RiskDocument.workspace_id == UUID(workspace_id)
                )
            )
        with Session(engine, expire_on_commit=False) as session:
            job, _ = create_full_restore_preview(
                session,
                context,
                payload,
                storage,
                mode=RestoreMode.MERGE,
                idempotency_key="same-workspace-preview",
            )
            session.commit()
            completed = confirm_full_restore(
                session,
                context,
                job.id,
                preview_id=job.preview_id,
                manifest_fingerprint=job.manifest_fingerprint,
                idempotency_key="same-workspace-confirm",
                storage=storage,
            )
            assert completed.status is FullRestoreStatus.SUCCEEDED
        with Session(engine) as session:
            after_assets = list(
                session.scalars(
                    select(ContentAsset).where(
                        ContentAsset.workspace_id == UUID(workspace_id)
                    )
                )
            )
            assert len(after_assets) == len(before_assets)
            assert {asset.object_key for asset in after_assets} == before_asset_keys
            assert (
                session.scalar(
                    select(RiskDocument.object_key).where(
                        RiskDocument.workspace_id == UUID(workspace_id)
                    )
                )
                == before_risk_key
            )

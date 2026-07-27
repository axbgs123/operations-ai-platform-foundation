from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.core.storage import StoredObject
from app.modules.content.models import Content, DeletedItem
from app.modules.exports.deletion import (
    DEFAULT_TRASH_RETENTION,
    ManagedObjectCleaner,
    RetentionService,
    RetentionStrategy,
    ResourcePurgeExpired,
    TrashService,
    WorkspaceDeletionBlocked,
    WorkspaceDeletionService,
    purge_expired_trash,
    process_workspace_deletion,
)
from app.modules.exports.models import (
    DeletionAudit,
    WorkspaceDeletionJob,
    WorkspaceDeletionPhase,
    WorkspaceDeletionStatus,
    ExportKind,
    ExportStatus,
    ExportTask,
    ManagedObject,
    ManagedObjectState,
)
from app.modules.exports.service import create_export_task, process_export_task
from app.modules.exports.deletion_router import get_deletion_enqueuer
from app.modules.imports.models import (
    ImportBatch,
    ImportBatchStatus,
    ImportSourceKind,
    ScreenshotRecognitionStatus,
)
from app.modules.metrics.models import ContentType
from app.modules.content.account_models import Platform
from app.modules.workspace.permissions import PermissionDenied
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember
from tests.imports.helpers import (
    configured_client,
    create_published_content,
    create_workspace_account,
)
from tests.exports.test_csv import _login_role


NOW = datetime(2026, 7, 26, 15, 0, tzinfo=UTC)


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_deletes = False

    def put_object(
        self,
        object_key: str,
        content: bytes,
        *,
        mime_type: str,
    ) -> None:
        self.objects[object_key] = content

    def get_object(self, object_key: str) -> bytes:
        return self.objects[object_key]

    def inspect_object(self, object_key: str) -> StoredObject | None:
        content = self.objects.get(object_key)
        return (
            StoredObject(size=len(content), mime_type="application/octet-stream")
            if content is not None
            else None
        )

    def delete_object(self, object_key: str) -> None:
        if self.fail_deletes:
            raise RuntimeError("synthetic object delete failure")
        self.objects.pop(object_key, None)


class MemoryCache:
    def __init__(self) -> None:
        self.cleared: list[UUID] = []
        self.fail = False

    def clear_workspace(self, workspace_id: UUID) -> None:
        if self.fail:
            raise RuntimeError("synthetic cache failure")
        self.cleared.append(workspace_id)


def _context(client, engine, workspace_id: str) -> WorkspaceContext:
    from app.modules.workspace.auth import InviteAuthService

    token = client.cookies.get("session")
    assert token is not None
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert context.workspace_id == UUID(workspace_id)
        return context


def test_content_trash_is_idempotent_recoverable_and_workspace_scoped() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="人工合成的回收站内容",
            work_url="https://example.invalid/synthetic-content",
        )
        context = _context(client, engine, workspace_id)
        other_workspace_id, _, _ = create_workspace_account(
            client,
            workspace_name="隔离工作区",
            platform="xiaohongshu",
        )

        with Session(engine, expire_on_commit=False) as session:
            service = TrashService(
                session,
                context,
                now=lambda: NOW,
            )
            first = service.soft_delete_content(
                UUID(content["id"]),
                reason="用户主动整理",
            )
            repeated = service.soft_delete_content(
                UUID(content["id"]),
                reason="重复请求不能产生新记录",
            )
            session.commit()

            assert first.id == repeated.id
            assert first.resource_type == "content"
            assert first.deleted_at == NOW
            assert first.scheduled_purge_at == NOW + DEFAULT_TRASH_RETENTION
            assert first.status.value == "recoverable"
            assert first.deletion_reason == "用户主动整理"
            assert len(service.list_items()) == 1

            other_context = WorkspaceContext(
                workspace_id=UUID(other_workspace_id),
                member_id=context.member_id,
                role="admin",
            )
            assert TrashService(session, other_context).list_items() == []
            with pytest.raises(LookupError):
                TrashService(session, other_context).restore_content(
                    UUID(content["id"])
                )

            restored = service.restore_content(UUID(content["id"]))
            repeated_restore = service.restore_content(UUID(content["id"]))
            session.commit()
            assert restored.id == repeated_restore.id
            assert restored.deleted_at is None
            assert first.status.value == "restored"
            assert first.restored_at == NOW


def test_expired_trash_cannot_be_restored_and_failed_restore_keeps_deleted() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="人工合成的过期内容",
            work_url=None,
        )
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            service = TrashService(session, context, now=lambda: NOW)
            item = service.soft_delete_content(UUID(content["id"]))
            session.commit()
            item.scheduled_purge_at = NOW - timedelta(seconds=1)
            session.commit()

            with pytest.raises(ResourcePurgeExpired):
                service.restore_content(UUID(content["id"]))
            session.rollback()
            persisted = session.get(Content, UUID(content["id"]))
            assert persisted is not None
            assert persisted.deleted_at == NOW
            persisted_item = session.get(DeletedItem, item.id)
            assert persisted_item is not None
            assert persisted_item.status.value == "recoverable"


def test_expired_trash_is_physically_purged_with_children_idempotently() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="到期清理的人工合成内容",
            work_url=None,
        )
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            item = TrashService(
                session, context, now=lambda: NOW
            ).soft_delete_content(UUID(content["id"]))
            item.scheduled_purge_at = NOW - timedelta(seconds=1)
            session.commit()
            assert purge_expired_trash(
                session, context.workspace_id, now=lambda: NOW
            ) == [item.id]
            session.commit()
            assert session.get(Content, UUID(content["id"])) is None
            assert session.get(DeletedItem, item.id).status.value == "purged"
            assert (
                purge_expired_trash(
                    session, context.workspace_id, now=lambda: NOW
                )
                == []
            )


def test_soft_delete_transaction_failure_rolls_back_content_and_trash_record() -> None:
    with configured_client() as (client, engine):
        workspace_id, csrf, account = create_workspace_account(client)
        content = create_published_content(
            client,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="人工合成的回滚内容",
            work_url=None,
        )
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            service = TrashService(session, context, now=lambda: NOW)
            with pytest.raises(RuntimeError, match="injected"):
                service.soft_delete_content(
                    UUID(content["id"]),
                    failure_injector=lambda _: (_ for _ in ()).throw(
                        RuntimeError("injected")
                    ),
                )
            session.rollback()
            persisted = session.get(Content, UUID(content["id"]))
            assert persisted is not None
            assert persisted.deleted_at is None
            assert (
                session.scalar(
                    select(DeletedItem).where(
                        DeletedItem.resource_id == UUID(content["id"])
                    )
                )
                is None
            )


def _screenshot_batch(
    session: Session,
    *,
    workspace_id: UUID,
    account_id: UUID,
) -> ImportBatch:
    batch = ImportBatch(
        workspace_id=workspace_id,
        account_id=account_id,
        platform=Platform.DOUYIN,
        content_type=ContentType.VIDEO,
        source_kind=ImportSourceKind.SCREENSHOT,
        status=ImportBatchStatus.CONFIRMED,
        recognition_status=ScreenshotRecognitionStatus.READY,
        screenshot_mime_type="image/png",
        screenshot_sha256="a" * 64,
        screenshot_bytes=b"synthetic screenshot bytes",
        screenshot_retention_policy="workspace_policy",
    )
    session.add(batch)
    session.flush()
    return batch


@pytest.mark.parametrize(
    ("strategy", "duration_seconds", "expected_state", "keeps_bytes"),
    [
        (RetentionStrategy.IMMEDIATE, None, ManagedObjectState.DELETED, False),
        (RetentionStrategy.SCHEDULED, 3600, ManagedObjectState.SCHEDULED, True),
        (RetentionStrategy.EVIDENCE, None, ManagedObjectState.EVIDENCE, True),
    ],
)
def test_workspace_versioned_screenshot_retention_policies(
    strategy: RetentionStrategy,
    duration_seconds: int | None,
    expected_state: ManagedObjectState,
    keeps_bytes: bool,
) -> None:
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            retention = RetentionService(
                session,
                context,
                now=lambda: NOW,
            )
            policy = retention.configure(
                strategy=strategy,
                retention_seconds=duration_seconds,
            )
            batch = _screenshot_batch(
                session,
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
            )
            record = retention.apply_screenshot_policy(
                batch,
                event="confirmed",
                evidence_reason=(
                    "关联人工确认快照"
                    if strategy is RetentionStrategy.EVIDENCE
                    else None
                ),
            )
            session.commit()

            assert policy.version == 1
            assert policy.effective_at == NOW
            assert record.policy_version == 1
            assert record.strategy is strategy
            assert record.state is expected_state
            assert (batch.screenshot_bytes is not None) is keeps_bytes
            assert record.object_key is None
            if strategy is RetentionStrategy.SCHEDULED:
                assert record.purge_at == NOW + timedelta(hours=1)
            if strategy is RetentionStrategy.EVIDENCE:
                assert record.evidence_reason == "关联人工确认快照"

            replacement = retention.configure(
                strategy=RetentionStrategy.IMMEDIATE,
                retention_seconds=None,
            )
            session.commit()
            assert replacement.version == 2
            assert record.policy_version == 1
            assert record.strategy is strategy


def test_retention_policy_requires_admin_and_valid_strategy_configuration() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            viewer = WorkspaceContext(
                workspace_id=context.workspace_id,
                member_id=context.member_id,
                role="viewer",
            )
            with pytest.raises(PermissionDenied):
                RetentionService(session, viewer).configure(
                    strategy=RetentionStrategy.IMMEDIATE,
                    retention_seconds=None,
                )
            with pytest.raises(ValueError):
                RetentionService(session, context).configure(
                    strategy=RetentionStrategy.SCHEDULED,
                    retention_seconds=0,
                )


def test_managed_object_cleanup_is_scoped_retryable_and_respects_active_claims() -> None:
    storage = MemoryStorage()
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        orphan_key = (
            f"workspaces/{workspace_id}/exports/"
            "00000000-0000-0000-0000-000000000001/old-claim/result.zip"
        )
        storage.objects[orphan_key] = b"isolated synthetic export"
        with Session(engine, expire_on_commit=False) as session:
            retention = RetentionService(
                session,
                context,
                now=lambda: NOW,
            )
            record = retention.register_managed_object(
                owner_type="export_job",
                owner_id=UUID("00000000-0000-0000-0000-000000000001"),
                object_key=orphan_key,
                managed_prefix=f"workspaces/{workspace_id}/exports/",
                purge_at=NOW - timedelta(seconds=1),
                claim_token="old-claim",
                lease_expires_at=NOW + timedelta(minutes=1),
            )
            session.commit()
            cleaner = ManagedObjectCleaner(
                session,
                storage,
                now=lambda: NOW,
            )
            assert cleaner.cleanup_due(context.workspace_id) == []
            assert orphan_key in storage.objects

            record.lease_expires_at = NOW - timedelta(seconds=1)
            session.commit()
            storage.fail_deletes = True
            failed = cleaner.cleanup_due(context.workspace_id)
            session.commit()
            assert failed == [record.id]
            assert record.state is ManagedObjectState.RETRYING
            assert orphan_key in storage.objects

            storage.fail_deletes = False
            record.purge_at = NOW - timedelta(seconds=1)
            cleaned = cleaner.cleanup_due(context.workspace_id)
            session.commit()
            assert cleaned == [record.id]
            assert record.state is ManagedObjectState.DELETED
            assert orphan_key not in storage.objects


def test_cleaner_refuses_business_references_wrong_prefix_and_other_workspace() -> None:
    storage = MemoryStorage()
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        other_workspace_id, _, _ = create_workspace_account(
            client,
            workspace_name="其他清理隔离工作区",
        )
        with Session(engine, expire_on_commit=False) as session:
            retention = RetentionService(session, context, now=lambda: NOW)
            with pytest.raises(ValueError):
                retention.register_managed_object(
                    owner_type="export_job",
                    owner_id=UUID("00000000-0000-0000-0000-000000000002"),
                    object_key="arbitrary-bucket-path/unsafe",
                    managed_prefix=f"workspaces/{workspace_id}/exports/",
                    purge_at=NOW,
                )
            referenced_key = f"workspaces/{workspace_id}/exports/safe/result.zip"
            other_key = (
                f"workspaces/{other_workspace_id}/exports/isolated/result.zip"
            )
            storage.objects[referenced_key] = b"referenced"
            storage.objects[other_key] = b"other"
            referenced = retention.register_managed_object(
                owner_type="export_job",
                owner_id=UUID("00000000-0000-0000-0000-000000000003"),
                object_key=referenced_key,
                managed_prefix=f"workspaces/{workspace_id}/exports/",
                purge_at=NOW - timedelta(seconds=1),
                business_referenced=True,
            )
            session.commit()
            assert (
                ManagedObjectCleaner(
                    session,
                    storage,
                    now=lambda: NOW,
                ).cleanup_due(context.workspace_id)
                == []
            )
            assert referenced.state is ManagedObjectState.REFERENCED
            assert referenced_key in storage.objects
            assert other_key in storage.objects


def test_export_lost_claim_leaves_registered_isolation_object_for_safe_cleanup() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            task, _ = create_export_task(
                session,
                context,
                kind=ExportKind.CSV,
                content_id=None,
                idempotency_key="lost-claim-export",
            )
            session.commit()
            task_id = task.id

        class ClaimStealingStorage(MemoryStorage):
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
                with Session(engine) as stealing_session:
                    stealing_session.execute(
                        update(ExportTask)
                        .where(ExportTask.id == task_id)
                        .values(
                            claim_token="replacement-claim",
                            lease_expires_at=NOW - timedelta(seconds=1),
                        )
                    )
                    stealing_session.commit()

        storage = ClaimStealingStorage()
        with Session(engine) as session:
            process_export_task(session, task_id, storage)

        with Session(engine, expire_on_commit=False) as session:
            task = session.get(ExportTask, task_id)
            assert task is not None
            assert task.status is ExportStatus.RUNNING
            assert task.object_key is None
            managed = session.scalar(
                select(ManagedObject).where(
                    ManagedObject.owner_type == "export_job",
                    ManagedObject.owner_id == task_id,
                )
            )
            assert managed is not None
            assert managed.state is ManagedObjectState.ACTIVE
            assert managed.object_key in storage.objects
            managed.purge_at = NOW - timedelta(seconds=1)
            managed.lease_expires_at = NOW - timedelta(seconds=1)
            session.commit()
            assert ManagedObjectCleaner(
                session,
                storage,
                now=lambda: NOW,
            ).cleanup_due(UUID(workspace_id)) == [managed.id]
            session.commit()
            assert managed.state is ManagedObjectState.DELETED
            assert storage.objects == {}


def test_workspace_deletion_confirmation_is_hashed_short_lived_and_one_time() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            service = WorkspaceDeletionService(
                session,
                context,
                now=lambda: NOW,
            )
            impact = service.impact()
            token, confirmation = service.request_confirmation()
            session.commit()

            assert impact.structured_records > 0
            assert impact.workspace_id == context.workspace_id
            assert token not in confirmation.token_hash
            assert confirmation.token_hash != token
            assert confirmation.expires_at == NOW + timedelta(minutes=10)

            job, created = service.confirm_deletion(
                token,
                idempotency_key="delete-workspace-once",
            )
            repeated, repeated_created = service.confirm_deletion(
                token,
                idempotency_key="delete-workspace-once",
            )
            session.commit()
            assert created
            assert not repeated_created
            assert repeated.id == job.id
            assert confirmation.used_at == NOW
            workspace = session.get(Workspace, context.workspace_id)
            assert workspace is not None
            assert workspace.status == "deletion_pending"

            with pytest.raises(ValueError, match="confirmation"):
                service.confirm_deletion(
                    token,
                    idempotency_key="different-confirmation",
                )


def test_confirmation_expires_and_role_or_workspace_version_change_invalidates_it() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        clock = [NOW]
        with Session(engine, expire_on_commit=False) as session:
            service = WorkspaceDeletionService(
                session,
                context,
                now=lambda: clock[0],
            )
            token, _ = service.request_confirmation()
            session.commit()
            clock[0] = NOW + timedelta(minutes=11)
            with pytest.raises(ValueError, match="expired"):
                service.confirm_deletion(
                    token,
                    idempotency_key="expired-confirmation",
                )
            session.rollback()

            clock[0] = NOW
            token, _ = service.request_confirmation()
            member = session.get(WorkspaceMember, context.member_id)
            assert member is not None
            member.role = MemberRole.EDITOR
            session.commit()
            with pytest.raises(PermissionDenied):
                service.confirm_deletion(
                    token,
                    idempotency_key="role-changed",
                )


def test_compensation_and_evidence_retention_block_workspace_deletion() -> None:
    from app.modules.exports.models import FullRestorePhase, FullRestoreStatus, RestoreJob

    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            restore = RestoreJob(
                workspace_id=context.workspace_id,
                requested_by=context.member_id,
                target_workspace_id=context.workspace_id,
                mode="merge",
                idempotency_key="blocked-restore",
                request_fingerprint="a" * 64,
                archive_sha256="b" * 64,
                archive_object_key=f"workspaces/{workspace_id}/restore/archive.zip",
                staging_prefix=f"workspaces/{workspace_id}/restore-staging/x",
                status=FullRestoreStatus.FAILED,
                phase=FullRestorePhase.COMPENSATION_REQUIRED,
                preview_id="preview",
                manifest_fingerprint="c" * 64,
                preview_json={},
                object_plan=[],
            )
            session.add(restore)
            session.flush()
            session.add(
                ManagedObject(
                    workspace_id=context.workspace_id,
                    owner_type="risk_evidence",
                    owner_id=restore.id,
                    managed_prefix=f"workspaces/{workspace_id}/evidence/",
                    policy_version=1,
                    strategy=RetentionStrategy.EVIDENCE,
                    state=ManagedObjectState.EVIDENCE,
                    object_key=f"workspaces/{workspace_id}/evidence/item.bin",
                    evidence_reason="合成审计证据",
                )
            )
            session.commit()
            service = WorkspaceDeletionService(session, context)
            impact = service.impact()
            assert impact.compensation_required_jobs == 1
            assert impact.evidence_retained_objects == 1
            with pytest.raises(WorkspaceDeletionBlocked):
                service.request_confirmation()


def test_workspace_deletion_phases_remove_private_state_without_touching_other_workspace() -> None:
    storage = MemoryStorage()
    cache = MemoryCache()
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        other_workspace_id, _, _ = create_workspace_account(
            client,
            workspace_name="必须保留的其他工作区",
            platform="xiaohongshu",
        )
        key = f"workspaces/{workspace_id}/contents/synthetic-cover.png"
        other_key = (
            f"workspaces/{other_workspace_id}/contents/other-cover.png"
        )
        storage.objects[key] = b"workspace-private-object"
        storage.objects[other_key] = b"other-workspace-object"

        with Session(engine, expire_on_commit=False) as session:
            from app.modules.content.models import AssetCategory, ContentAsset

            workspace_content = session.scalar(
                select(Content).where(
                    Content.workspace_id == UUID(workspace_id)
                )
            )
            if workspace_content is None:
                workspace_content = Content(
                    workspace_id=UUID(workspace_id),
                    account_id=UUID(account["id"]),
                    platform=Platform.DOUYIN,
                    content_type=ContentType.VIDEO,
                    title="合成删除内容",
                    body="合成正文",
                    objective_profile_id=UUID(account["objective_profile"]["id"]),
                    benchmark_profile_id=UUID(account["benchmark_profile"]["id"]),
                )
                session.add(workspace_content)
                session.flush()
            session.add(
                ContentAsset(
                    workspace_id=UUID(workspace_id),
                    content_id=workspace_content.id,
                    category=AssetCategory.COVER,
                    object_key=key,
                    file_name="synthetic-cover.png",
                    mime_type="image/png",
                    size=len(storage.objects[key]),
                )
            )
            service = WorkspaceDeletionService(
                session,
                context,
                now=lambda: NOW,
            )
            token, _ = service.request_confirmation()
            job, _ = service.confirm_deletion(
                token,
                idempotency_key="delete-completely",
            )
            session.commit()
            job_id = job.id

        with Session(engine) as session:
            process_workspace_deletion(
                session,
                job_id,
                storage,
                cache,
                now=lambda: NOW,
            )

        with Session(engine) as session:
            job = session.get(WorkspaceDeletionJob, job_id)
            assert job is not None
            assert job.status is WorkspaceDeletionStatus.SUCCEEDED
            assert job.phase is WorkspaceDeletionPhase.COMPLETED
            assert session.get(Workspace, UUID(workspace_id)) is None
            assert session.get(Workspace, UUID(other_workspace_id)) is not None
            assert key not in storage.objects
            assert other_key in storage.objects
            assert cache.cleared == [UUID(workspace_id)]
            assert session.scalar(
                select(DeletionAudit).where(
                    DeletionAudit.deletion_job_id == job_id,
                    DeletionAudit.phase == "completed",
                )
            ) is not None


def test_workspace_deletion_cache_failure_retries_without_reopening_workspace() -> None:
    storage = MemoryStorage()
    cache = MemoryCache()
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine, expire_on_commit=False) as session:
            service = WorkspaceDeletionService(
                session,
                context,
                now=lambda: NOW,
            )
            token, _ = service.request_confirmation()
            job, _ = service.confirm_deletion(
                token,
                idempotency_key="retry-deletion",
            )
            session.commit()
            job_id = job.id
        cache.fail = True
        with Session(engine) as session:
            process_workspace_deletion(
                session,
                job_id,
                storage,
                cache,
                now=lambda: NOW,
            )
        with Session(engine) as session:
            job = session.get(WorkspaceDeletionJob, job_id)
            workspace = session.get(Workspace, UUID(workspace_id))
            assert job is not None
            assert job.status is WorkspaceDeletionStatus.RETRYING
            assert job.phase is WorkspaceDeletionPhase.CACHES_DELETING
            assert workspace is not None
            assert workspace.status == "deletion_pending"

        cache.fail = False
        with Session(engine) as session:
            process_workspace_deletion(
                session,
                job_id,
                storage,
                cache,
                now=lambda: NOW + timedelta(minutes=6),
            )
        with Session(engine) as session:
            job = session.get(WorkspaceDeletionJob, job_id)
            assert job is not None
            assert job.status is WorkspaceDeletionStatus.SUCCEEDED
            assert session.get(Workspace, UUID(workspace_id)) is None


def test_workspace_object_delete_failure_is_retryable_and_keeps_workspace_closed() -> None:
    storage = MemoryStorage()
    cache = MemoryCache()
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        key = f"workspaces/{workspace_id}/contents/failure.png"
        storage.objects[key] = b"synthetic"
        with Session(engine) as session:
            from app.modules.content.models import AssetCategory, ContentAsset

            content = Content(
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
                platform=Platform.DOUYIN,
                content_type=ContentType.VIDEO,
                title="对象删除失败",
                body="人工合成",
                objective_profile_id=UUID(account["objective_profile"]["id"]),
                benchmark_profile_id=UUID(account["benchmark_profile"]["id"]),
            )
            session.add(content)
            session.flush()
            session.add(
                ContentAsset(
                    workspace_id=context.workspace_id,
                    content_id=content.id,
                    category=AssetCategory.COVER,
                    object_key=key,
                    file_name="failure.png",
                    mime_type="image/png",
                    size=9,
                )
            )
            service = WorkspaceDeletionService(session, context, now=lambda: NOW)
            token, _ = service.request_confirmation()
            job, _ = service.confirm_deletion(
                token, idempotency_key="object-delete-failure"
            )
            session.commit()
            job_id = job.id

        storage.fail_deletes = True
        with Session(engine) as session:
            process_workspace_deletion(
                session, job_id, storage, cache, now=lambda: NOW
            )
        with Session(engine) as session:
            job = session.get(WorkspaceDeletionJob, job_id)
            workspace = session.get(Workspace, context.workspace_id)
            assert job is not None
            assert job.status is WorkspaceDeletionStatus.RETRYING
            assert job.phase is WorkspaceDeletionPhase.OBJECTS_DELETING
            assert workspace is not None
            assert workspace.status == "deletion_pending"
            assert key in storage.objects


def test_old_worker_stops_after_losing_deletion_claim() -> None:
    storage = MemoryStorage()
    cache = MemoryCache()
    with configured_client() as (client, engine):
        workspace_id, _, account = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        key = f"workspaces/{workspace_id}/contents/fenced.png"
        storage.objects[key] = b"synthetic"
        with Session(engine) as session:
            from app.modules.content.models import AssetCategory, ContentAsset

            content = Content(
                workspace_id=context.workspace_id,
                account_id=UUID(account["id"]),
                platform=Platform.DOUYIN,
                content_type=ContentType.VIDEO,
                title="Worker fencing",
                body="人工合成",
                objective_profile_id=UUID(account["objective_profile"]["id"]),
                benchmark_profile_id=UUID(account["benchmark_profile"]["id"]),
            )
            session.add(content)
            session.flush()
            session.add(
                ContentAsset(
                    workspace_id=context.workspace_id,
                    content_id=content.id,
                    category=AssetCategory.COVER,
                    object_key=key,
                    file_name="fenced.png",
                    mime_type="image/png",
                    size=9,
                )
            )
            service = WorkspaceDeletionService(session, context, now=lambda: NOW)
            token, _ = service.request_confirmation()
            job, _ = service.confirm_deletion(
                token, idempotency_key="fence-old-worker"
            )
            session.commit()
            job_id = job.id

        stolen = False

        def steal_claim(phase: str) -> None:
            nonlocal stolen
            if phase != "objects_deleting" or stolen:
                return
            stolen = True
            with Session(engine) as rival:
                rival.execute(
                    update(WorkspaceDeletionJob)
                    .where(WorkspaceDeletionJob.id == job_id)
                    .values(claim_token="replacement-worker")
                )
                rival.commit()

        with Session(engine) as session:
            process_workspace_deletion(
                session,
                job_id,
                storage,
                cache,
                now=lambda: NOW,
                failure_injector=steal_claim,
            )
        with Session(engine) as session:
            job = session.get(WorkspaceDeletionJob, job_id)
            assert job is not None
            assert job.claim_token == "replacement-worker"
            assert job.status is WorkspaceDeletionStatus.RUNNING
            assert key in storage.objects
            workspace = session.get(Workspace, context.workspace_id)
            assert workspace is not None
            assert workspace.status == "deletion_pending"


def test_residual_check_failure_never_reports_workspace_deletion_success() -> None:
    with configured_client() as (client, engine):
        workspace_id, _, _ = create_workspace_account(client)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            service = WorkspaceDeletionService(session, context, now=lambda: NOW)
            token, _ = service.request_confirmation()
            job, _ = service.confirm_deletion(
                token, idempotency_key="residual-check-failure"
            )
            session.commit()
            job_id = job.id

        def fail_residual(phase: str) -> None:
            if phase == "residual_check":
                raise RuntimeError("synthetic residual")

        with Session(engine) as session:
            process_workspace_deletion(
                session,
                job_id,
                MemoryStorage(),
                MemoryCache(),
                now=lambda: NOW,
                failure_injector=fail_residual,
            )
        with Session(engine) as session:
            job = session.get(WorkspaceDeletionJob, job_id)
            assert job is not None
            assert job.status is WorkspaceDeletionStatus.RETRYING
            assert job.phase is WorkspaceDeletionPhase.STRUCTURED_DATA_DELETED
            assert job.completed_at is None


def test_deletion_management_api_enforces_roles_scope_and_stable_contracts() -> None:
    queued: list[UUID] = []
    with configured_client() as (admin, _):
        from app.main import app

        app.dependency_overrides[get_deletion_enqueuer] = lambda: queued.append
        workspace_id, csrf, account = create_workspace_account(admin)
        content = create_published_content(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            account=account,
            title="合成管理接口内容",
            work_url=None,
        )
        editor = _login_role(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            role="editor",
        )
        viewer = _login_role(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            role="viewer",
        )

        assert viewer.post(
            f"/v1/workspaces/{workspace_id}/trash/contents/{content['id']}",
        ).status_code == 403
        deleted = editor.post(
            f"/v1/workspaces/{workspace_id}/trash/contents/{content['id']}",
            json={"reason": "合成删除理由"},
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["data"]["status"] == "recoverable"
        trash = viewer.get(f"/v1/workspaces/{workspace_id}/trash")
        assert trash.status_code == 200
        assert [row["resource_id"] for row in trash.json()["data"]] == [
            content["id"]
        ]
        restored = editor.post(
            f"/v1/workspaces/{workspace_id}/trash/contents/{content['id']}/restore"
        )
        assert restored.status_code == 200
        assert restored.json()["data"]["deleted_at"] is None

        policy = admin.put(
            f"/v1/workspaces/{workspace_id}/retention-policy",
            headers={"X-CSRF-Token": csrf},
            json={"strategy": "scheduled", "retention_seconds": 3600},
        )
        assert policy.status_code == 200, policy.text
        assert policy.json()["data"]["version"] == 1
        assert viewer.put(
            f"/v1/workspaces/{workspace_id}/retention-policy",
            json={"strategy": "immediate", "retention_seconds": None},
        ).status_code == 403

        impact = admin.get(
            f"/v1/workspaces/{workspace_id}/deletion-impact"
        )
        assert impact.status_code == 200
        assert impact.json()["data"]["structured_records"] > 0
        confirmation = admin.post(
            f"/v1/workspaces/{workspace_id}/deletion-confirmations",
            headers={"X-CSRF-Token": csrf},
        )
        assert confirmation.status_code == 201, confirmation.text
        raw_token = confirmation.json()["data"]["confirmation_token"]
        assert raw_token
        confirmed = admin.post(
            f"/v1/workspaces/{workspace_id}/deletions",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "api-delete-workspace",
            },
            json={"confirmation_token": raw_token},
        )
        assert confirmed.status_code == 202, confirmed.text
        assert confirmed.json()["data"]["status"] == "queued"
        assert queued == [UUID(confirmed.json()["data"]["id"])]

        other_workspace_id, _, _ = create_workspace_account(
            viewer,
            workspace_name="API隔离工作区",
        )
        assert viewer.get(
            f"/v1/workspaces/{other_workspace_id}/trash"
        ).status_code == 200
        assert viewer.get(
            f"/v1/workspaces/{workspace_id}/trash"
        ).status_code == 404

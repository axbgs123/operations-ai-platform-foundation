from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import secrets
from typing import Protocol, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import WorkspaceContext
from app.core.storage import Storage
from app.modules.content.models import (
    Content,
    ContentAsset,
    DeletedItem,
    DeletedItemStatus,
)
from app.modules.exports.models import (
    ExportTask,
    ExportStatus,
    FullRestorePhase,
    FullRestoreStatus,
    DeletionAudit,
    ManagedObject,
    ManagedObjectState,
    RestoreJob,
    RetentionPolicy,
    RetentionStrategy,
    WorkspaceDeletionConfirmation,
    WorkspaceDeletionJob,
    WorkspaceDeletionPhase,
    WorkspaceDeletionStatus,
)
from app.modules.imports.capture_models import CaptureTask, CaptureTaskStatus
from app.modules.imports.capture_service import clear_task_object
from app.modules.imports.models import ExtensionToken, ImportBatch
from app.modules.operations_agent.models import (
    AgentArtifact,
    AgentBriefing,
    AgentConfirmation,
    AgentEvent,
    AgentPlan,
    AgentRun,
    AgentRunStep,
)
from app.modules.risk_rag.models import RiskChunkEmbedding, RiskDocument
from app.modules.workspace.models import (
    AuditLog,
    MemberRole,
    Workspace,
    WorkspaceAccessCode,
    WorkspaceMember,
    WorkspaceSession,
)
from app.modules.workspace.permissions import (
    Permission,
    PermissionDenied,
    require_permission,
)


DEFAULT_TRASH_RETENTION = timedelta(days=30)


class ResourcePurgeExpired(ValueError):
    pass


class WorkspaceDeletionBlocked(ValueError):
    pass


class DeletionClaimLost(RuntimeError):
    pass


class WorkspaceDeletionImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: UUID
    structured_records: int
    assets: int
    private_knowledge_documents: int
    vectors: int
    staging_tasks: int
    cache_prefixes: tuple[str, ...]
    compensation_required_jobs: int
    evidence_retained_objects: int


class CacheCleaner(Protocol):
    def clear_workspace(self, workspace_id: UUID) -> None: ...


WORKSPACE_DELETION_LEASE = timedelta(minutes=5)
CONFIRMATION_LIFETIME = timedelta(minutes=10)
PRIVATE_WORKSPACE_TABLES = (
    "workspace_members",
    "workspace_access_codes",
    "workspace_sessions",
    "audit_logs",
    "platform_accounts",
    "objective_profiles",
    "benchmark_profiles",
    "columns_campaigns",
    "contents",
    "content_assets",
    "deleted_items",
    "metric_definitions",
    "data_snapshots",
    "snapshot_metric_values",
    "metric_outbox_events",
    "benchmark_runs",
    "import_batches",
    "import_rows",
    "extension_tokens",
    "extension_capture_tasks",
    "viral_threshold_profiles",
    "viral_candidates",
    "viral_library_items",
    "analysis_runs",
    "account_analysis_settings",
    "analysis_suggestions",
    "product_events",
    "model_configs",
    "style_samples",
    "account_style_profiles",
    "fact_sources",
    "fact_items",
    "text_generation_runs",
    "cover_artifact_attempts",
    "cover_generation_runs",
    "risk_documents",
    "risk_chunks",
    "risk_chunk_embeddings",
    "risk_scans",
    "risk_scan_feedback",
    "risk_feedback_events",
    "export_jobs",
    "restore_jobs",
    "knowledge_index_rebuilds",
    "retention_policies",
    "managed_objects",
    "agent_briefings",
    "agent_plans",
    "agent_runs",
    "agent_run_steps",
    "agent_confirmations",
    "agent_artifacts",
    "agent_events",
    "agent_chat_sessions",
    "agent_chat_messages",
)


def _safe_count(session: Session, model, workspace_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.workspace_id == workspace_id)
        )
        or 0
    )


class WorkspaceDeletionService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._now = now or (lambda: datetime.now(UTC))

    def _require_admin(self) -> tuple[Workspace, WorkspaceMember]:
        require_permission(self._context.role, Permission.MANAGE_MEMBERS)
        if self._context.role != "admin" or self._context.member_id is None:
            raise PermissionDenied("admin role required")
        workspace = self._session.scalar(
            select(Workspace).where(
                Workspace.id == self._context.workspace_id
            )
        )
        member = self._session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == self._context.member_id,
                WorkspaceMember.workspace_id == self._context.workspace_id,
                WorkspaceMember.role == MemberRole.ADMIN,
                WorkspaceMember.revoked_at.is_(None),
            )
        )
        if workspace is None:
            raise LookupError("workspace not found")
        if member is None:
            raise PermissionDenied("admin membership is no longer active")
        return workspace, member

    def impact(self) -> WorkspaceDeletionImpact:
        from app.modules.generation.models import (
            CoverArtifactAttempt,
            CoverGenerationRun,
        )

        self._require_admin()
        workspace_id = self._context.workspace_id
        structured = sum(
            _safe_count(self._session, model, workspace_id)
            for model in (
                WorkspaceMember,
                WorkspaceAccessCode,
                WorkspaceSession,
                Content,
                ContentAsset,
                ImportBatch,
                ExtensionToken,
                CaptureTask,
                ExportTask,
                RestoreJob,
                RiskDocument,
                RiskChunkEmbedding,
                CoverGenerationRun,
                CoverArtifactAttempt,
                AgentBriefing,
                AgentPlan,
                AgentRun,
                AgentRunStep,
                AgentConfirmation,
                AgentArtifact,
                AgentEvent,
            )
        )
        return WorkspaceDeletionImpact(
            workspace_id=workspace_id,
            structured_records=structured,
            assets=_safe_count(self._session, ContentAsset, workspace_id),
            private_knowledge_documents=_safe_count(
                self._session,
                RiskDocument,
                workspace_id,
            ),
            vectors=_safe_count(
                self._session,
                RiskChunkEmbedding,
                workspace_id,
            ),
            staging_tasks=(
                _safe_count(self._session, ImportBatch, workspace_id)
                + _safe_count(self._session, CaptureTask, workspace_id)
                + _safe_count(self._session, RestoreJob, workspace_id)
            ),
            cache_prefixes=(f"workspace:{workspace_id}:",),
            compensation_required_jobs=int(
                self._session.scalar(
                    select(func.count())
                    .select_from(RestoreJob)
                    .where(
                        RestoreJob.workspace_id == workspace_id,
                        RestoreJob.phase
                        == FullRestorePhase.COMPENSATION_REQUIRED,
                    )
                )
                or 0
            ),
            evidence_retained_objects=int(
                self._session.scalar(
                    select(func.count())
                    .select_from(ManagedObject)
                    .where(
                        ManagedObject.workspace_id == workspace_id,
                        ManagedObject.state == ManagedObjectState.EVIDENCE,
                    )
                )
                or 0
            ),
        )

    def request_confirmation(
        self,
    ) -> tuple[str, WorkspaceDeletionConfirmation]:
        workspace, member = self._require_admin()
        impact = self.impact()
        if (
            impact.compensation_required_jobs
            or impact.evidence_retained_objects
        ):
            raise WorkspaceDeletionBlocked(
                "workspace deletion has protected retained state"
            )
        if workspace.status != "active":
            raise WorkspaceDeletionBlocked("workspace is not active")
        raw_token = secrets.token_urlsafe(32)
        confirmation = WorkspaceDeletionConfirmation(
            workspace_id=workspace.id,
            requested_by=member.id,
            action="workspace.delete",
            workspace_version=workspace.deletion_version,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=self._now() + CONFIRMATION_LIFETIME,
        )
        self._session.add(confirmation)
        self._session.flush()
        return raw_token, confirmation

    def confirm_deletion(
        self,
        token: str,
        *,
        idempotency_key: str,
    ) -> tuple[WorkspaceDeletionJob, bool]:
        workspace, member = self._require_admin()
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("invalid deletion idempotency key")
        existing = self._session.scalar(
            select(WorkspaceDeletionJob).where(
                WorkspaceDeletionJob.workspace_id == workspace.id,
                WorkspaceDeletionJob.requested_by == member.id,
                WorkspaceDeletionJob.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, False
        digest = hashlib.sha256(token.encode()).hexdigest()
        confirmation = self._session.scalar(
            select(WorkspaceDeletionConfirmation).where(
                WorkspaceDeletionConfirmation.workspace_id == workspace.id,
                WorkspaceDeletionConfirmation.requested_by == member.id,
                WorkspaceDeletionConfirmation.action == "workspace.delete",
                WorkspaceDeletionConfirmation.token_hash == digest,
            )
        )
        if confirmation is None or not hmac.compare_digest(
            confirmation.token_hash,
            digest,
        ):
            raise ValueError("deletion confirmation invalid")
        if confirmation.used_at is not None:
            raise ValueError("deletion confirmation already used")
        if confirmation.expires_at <= self._now():
            raise ValueError("deletion confirmation expired")
        if confirmation.workspace_version != workspace.deletion_version:
            raise ValueError("deletion confirmation invalid")
        impact = self.impact()
        if (
            impact.compensation_required_jobs
            or impact.evidence_retained_objects
        ):
            raise WorkspaceDeletionBlocked(
                "workspace deletion has protected retained state"
            )
        object_keys = self._object_inventory(workspace.id)
        fingerprint = hashlib.sha256(
            (
                f"{workspace.id}:{member.id}:{workspace.deletion_version}:"
                f"{idempotency_key}"
            ).encode()
        ).hexdigest()
        job = WorkspaceDeletionJob(
            workspace_id=workspace.id,
            requested_by=member.id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            inventory={
                **impact.model_dump(mode="json"),
                "object_keys": object_keys,
            },
            status=WorkspaceDeletionStatus.QUEUED,
            phase=WorkspaceDeletionPhase.INVENTORY_CREATED,
        )
        self._session.add(job)
        confirmation.used_at = self._now()
        workspace.status = "deletion_pending"
        workspace.deletion_version += 1
        self._session.execute(
            update(WorkspaceSession)
            .where(WorkspaceSession.workspace_id == workspace.id)
            .values(revoked_at=self._now())
        )
        self._session.execute(
            update(WorkspaceAccessCode)
            .where(WorkspaceAccessCode.workspace_id == workspace.id)
            .values(revoked_at=self._now())
        )
        self._session.execute(
            update(ExtensionToken)
            .where(ExtensionToken.workspace_id == workspace.id)
            .values(revoked_at=self._now())
        )
        self._session.flush()
        self._audit(
            job,
            phase=WorkspaceDeletionPhase.INVENTORY_CREATED,
            status="succeeded",
        )
        return job, True

    def _object_inventory(self, workspace_id: UUID) -> list[str]:
        keys: set[str] = set()
        keys.update(
            self._session.scalars(
                select(ContentAsset.object_key).where(
                    ContentAsset.workspace_id == workspace_id
                )
            )
        )
        keys.update(
            key
            for key in self._session.scalars(
                select(RiskDocument.object_key).where(
                    RiskDocument.workspace_id == workspace_id,
                    RiskDocument.object_key.is_not(None),
                )
            )
            if key is not None
        )
        keys.update(
            key
            for key in self._session.scalars(
                select(ExportTask.object_key).where(
                    ExportTask.workspace_id == workspace_id,
                    ExportTask.object_key.is_not(None),
                )
            )
            if key is not None
        )
        keys.update(
            key
            for key in self._session.scalars(
                select(ManagedObject.object_key).where(
                    ManagedObject.workspace_id == workspace_id,
                    ManagedObject.object_key.is_not(None),
                )
            )
            if key is not None
        )
        keys.update(
            self._session.scalars(
                select(CaptureTask.object_key).where(
                    CaptureTask.workspace_id == workspace_id
                )
            )
        )
        for restore_job in self._session.scalars(
            select(RestoreJob).where(RestoreJob.workspace_id == workspace_id)
        ):
            keys.add(restore_job.archive_object_key)
            for item in restore_job.object_plan:
                for field in ("staging_key", "final_key"):
                    raw_key = item.get(field)
                    if isinstance(raw_key, str):
                        keys.add(raw_key)
        root = f"workspaces/{workspace_id}/"
        return sorted(key for key in keys if key.startswith(root))

    def _audit(
        self,
        job: WorkspaceDeletionJob,
        *,
        phase: WorkspaceDeletionPhase,
        status: str,
        error_code: str | None = None,
    ) -> None:
        self._session.add(
            DeletionAudit(
                workspace_id=job.workspace_id,
                actor_id=job.requested_by,
                deletion_job_id=job.id,
                operation="workspace.delete",
                resource_type="workspace",
                resource_id=job.workspace_id,
                phase=phase.value,
                status=status,
                error_code=error_code,
                created_at=self._now(),
            )
        )


def _assert_deletion_claim(
    session: Session,
    job_id: UUID,
    claim_token: str,
) -> WorkspaceDeletionJob:
    job = session.scalar(
        select(WorkspaceDeletionJob).where(
            WorkspaceDeletionJob.id == job_id,
            WorkspaceDeletionJob.status == WorkspaceDeletionStatus.RUNNING,
            WorkspaceDeletionJob.claim_token == claim_token,
        )
    )
    if job is None:
        raise DeletionClaimLost("workspace deletion claim lost")
    return job


def _deletion_audit(
    session: Session,
    job: WorkspaceDeletionJob,
    phase: WorkspaceDeletionPhase,
    status: str,
    now: datetime,
    error_code: str | None = None,
) -> None:
    session.add(
        DeletionAudit(
            workspace_id=job.workspace_id,
            actor_id=job.requested_by,
            deletion_job_id=job.id,
            operation="workspace.delete",
            resource_type="workspace",
            resource_id=job.workspace_id,
            phase=phase.value,
            status=status,
            error_code=error_code,
            created_at=now,
        )
    )


def process_workspace_deletion(
    session: Session,
    job_id: UUID,
    storage: Storage,
    cache: CacheCleaner,
    *,
    now: Callable[[], datetime] | None = None,
    failure_injector: Callable[[str], None] | None = None,
) -> None:
    clock = now or (lambda: datetime.now(UTC))
    current = clock()
    claim_token = secrets.token_hex(16)
    claimed = cast(
        CursorResult,
        session.execute(
            update(WorkspaceDeletionJob)
            .where(
                WorkspaceDeletionJob.id == job_id,
                or_(
                    WorkspaceDeletionJob.status.in_(
                        [
                            WorkspaceDeletionStatus.QUEUED,
                            WorkspaceDeletionStatus.RETRYING,
                        ]
                    ),
                    (
                        (WorkspaceDeletionJob.status == WorkspaceDeletionStatus.RUNNING)
                        & WorkspaceDeletionJob.lease_expires_at.is_not(None)
                        & (WorkspaceDeletionJob.lease_expires_at <= current)
                    ),
                ),
            )
            .values(
                status=WorkspaceDeletionStatus.RUNNING,
                claim_token=claim_token,
                lease_expires_at=current + WORKSPACE_DELETION_LEASE,
            )
        ),
    )
    if claimed.rowcount != 1:
        session.rollback()
        return
    session.commit()
    try:
        job = _assert_deletion_claim(session, job_id, claim_token)
        workspace_id = job.workspace_id
        job.phase = WorkspaceDeletionPhase.ACCESS_REVOKED
        _deletion_audit(
            session, job, job.phase, "succeeded", clock()
        )
        session.commit()

        job = _assert_deletion_claim(session, job_id, claim_token)
        session.execute(
            update(CaptureTask)
            .where(
                CaptureTask.workspace_id == workspace_id,
                CaptureTask.status.in_(
                    [
                        CaptureTaskStatus.QUEUED,
                        CaptureTaskStatus.RUNNING,
                        CaptureTaskStatus.RETRYING,
                    ]
                ),
            )
            .values(status=CaptureTaskStatus.CANCELLED)
        )
        session.execute(
            update(ExportTask)
            .where(
                ExportTask.workspace_id == workspace_id,
                ExportTask.status.in_(
                    [ExportStatus.QUEUED, ExportStatus.RUNNING]
                ),
            )
            .values(
                status=ExportStatus.FAILED,
                error_code="workspace_deletion",
                claim_token=None,
                lease_expires_at=None,
            )
        )
        session.execute(
            update(RestoreJob)
            .where(
                RestoreJob.workspace_id == workspace_id,
                RestoreJob.status.in_(
                    [
                        FullRestoreStatus.QUEUED,
                        FullRestoreStatus.RUNNING,
                        FullRestoreStatus.RETRYING,
                    ]
                ),
            )
            .values(
                status=FullRestoreStatus.CANCELLED,
                claim_token=None,
                lease_expires_at=None,
            )
        )
        job.phase = WorkspaceDeletionPhase.JOBS_CANCELLED
        _deletion_audit(session, job, job.phase, "succeeded", clock())
        session.commit()

        job = _assert_deletion_claim(session, job_id, claim_token)
        session.execute(
            delete(RiskChunkEmbedding).where(
                RiskChunkEmbedding.workspace_id == workspace_id
            )
        )
        job.phase = WorkspaceDeletionPhase.VECTORS_DELETED
        _deletion_audit(session, job, job.phase, "succeeded", clock())
        session.commit()

        job = _assert_deletion_claim(session, job_id, claim_token)
        job.phase = WorkspaceDeletionPhase.OBJECTS_DELETING
        session.commit()
        for raw_key in cast(list[object], job.inventory.get("object_keys", [])):
            _assert_deletion_claim(session, job_id, claim_token)
            key = str(raw_key)
            if not key.startswith(f"workspaces/{workspace_id}/"):
                raise RuntimeError("object inventory escaped workspace")
            if failure_injector is not None:
                failure_injector("objects_deleting")
            _assert_deletion_claim(session, job_id, claim_token)
            storage.delete_object(key)
            _assert_deletion_claim(session, job_id, claim_token)
        for capture_task in session.scalars(
            select(CaptureTask).where(
                CaptureTask.workspace_id == workspace_id
            )
        ):
            clear_task_object(capture_task)
        job = _assert_deletion_claim(session, job_id, claim_token)
        job.phase = WorkspaceDeletionPhase.OBJECTS_DELETED
        _deletion_audit(session, job, job.phase, "succeeded", clock())
        session.commit()

        job = _assert_deletion_claim(session, job_id, claim_token)
        job.phase = WorkspaceDeletionPhase.CACHES_DELETING
        session.commit()
        if failure_injector is not None:
            failure_injector("caches_deleting")
        _assert_deletion_claim(session, job_id, claim_token)
        cache.clear_workspace(workspace_id)
        job = _assert_deletion_claim(session, job_id, claim_token)
        job.phase = WorkspaceDeletionPhase.CACHES_DELETED
        _deletion_audit(session, job, job.phase, "succeeded", clock())
        session.commit()

        job = _assert_deletion_claim(session, job_id, claim_token)
        job.phase = WorkspaceDeletionPhase.STRUCTURED_DATA_DELETING
        session.commit()
        session.execute(
            delete(WorkspaceDeletionConfirmation).where(
                WorkspaceDeletionConfirmation.workspace_id == workspace_id
            )
        )
        workspace = session.get(Workspace, workspace_id)
        if workspace is not None:
            session.delete(workspace)
        session.commit()
        persisted_job = session.get(WorkspaceDeletionJob, job_id)
        assert persisted_job is not None
        job = persisted_job
        job.phase = WorkspaceDeletionPhase.STRUCTURED_DATA_DELETED
        _deletion_audit(session, job, job.phase, "succeeded", clock())
        session.commit()
        if failure_injector is not None:
            failure_injector("residual_check")
        residual_tables: list[str] = []
        for table_name in PRIVATE_WORKSPACE_TABLES:
            table = Base.metadata.tables.get(table_name)
            if table is None or "workspace_id" not in table.c:
                continue
            remaining = int(
                session.scalar(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.workspace_id == workspace_id)
                )
                or 0
            )
            if remaining:
                residual_tables.append(table_name)
        if (
            session.get(Workspace, workspace_id) is not None
            or residual_tables
        ):
            raise RuntimeError("workspace residual data remains")
        for raw_key in cast(list[object], job.inventory.get("object_keys", [])):
            if storage.inspect_object(str(raw_key)) is not None:
                raise RuntimeError("workspace object residual remains")
        job.inventory = {**job.inventory, "object_keys": []}
        job.status = WorkspaceDeletionStatus.SUCCEEDED
        job.phase = WorkspaceDeletionPhase.COMPLETED
        job.error_code = None
        job.completed_at = clock()
        job.claim_token = None
        job.lease_expires_at = None
        _deletion_audit(session, job, job.phase, "succeeded", clock())
        session.commit()
    except DeletionClaimLost:
        session.rollback()
    except Exception:
        session.rollback()
        result = cast(
            CursorResult,
            session.execute(
                update(WorkspaceDeletionJob)
                .where(
                    WorkspaceDeletionJob.id == job_id,
                    WorkspaceDeletionJob.claim_token == claim_token,
                )
                .values(
                    status=WorkspaceDeletionStatus.RETRYING,
                    error_code="WORKSPACE_DELETION_RETRY_REQUIRED",
                    claim_token=None,
                    lease_expires_at=None,
                )
            ),
        )
        if result.rowcount:
            failed = session.get(WorkspaceDeletionJob, job_id)
            assert failed is not None
            _deletion_audit(
                session,
                failed,
                failed.phase,
                "retrying",
                clock(),
                failed.error_code,
            )
        session.commit()


class RetentionService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._now = now or (lambda: datetime.now(UTC))

    def current_policy(self) -> RetentionPolicy | None:
        return self._session.scalar(
            select(RetentionPolicy)
            .where(
                RetentionPolicy.workspace_id == self._context.workspace_id,
                RetentionPolicy.effective_at <= self._now(),
            )
            .order_by(
                RetentionPolicy.version.desc(),
                RetentionPolicy.id.desc(),
            )
        )

    def configure(
        self,
        *,
        strategy: RetentionStrategy,
        retention_seconds: int | None,
    ) -> RetentionPolicy:
        require_permission(self._context.role, Permission.MANAGE_MEMBERS)
        if strategy is RetentionStrategy.SCHEDULED:
            if retention_seconds is None or retention_seconds <= 0:
                raise ValueError("scheduled retention requires a duration")
        elif retention_seconds is not None:
            raise ValueError("only scheduled retention accepts a duration")
        latest = self._session.scalar(
            select(func.max(RetentionPolicy.version)).where(
                RetentionPolicy.workspace_id == self._context.workspace_id
            )
        )
        policy = RetentionPolicy(
            workspace_id=self._context.workspace_id,
            version=int(latest or 0) + 1,
            strategy=strategy,
            effective_at=self._now(),
            retention_seconds=retention_seconds,
            created_by=self._context.member_id,
        )
        self._session.add(policy)
        self._session.flush()
        return policy

    def apply_screenshot_policy(
        self,
        batch: ImportBatch,
        *,
        event: str,
        evidence_reason: str | None = None,
    ) -> ManagedObject:
        if (
            batch.workspace_id != self._context.workspace_id
            or batch.source_kind.value != "screenshot"
        ):
            raise LookupError("screenshot batch not found")
        if event not in {"confirmed", "cancelled", "failed", "expired"}:
            raise ValueError("unsupported screenshot lifecycle event")
        policy = self.current_policy()
        if policy is None:
            legacy_strategy = {
                "retain_as_evidence": RetentionStrategy.EVIDENCE,
                "retain_for_period": RetentionStrategy.SCHEDULED,
            }.get(
                batch.screenshot_retention_policy or "",
                RetentionStrategy.IMMEDIATE,
            )
            policy = RetentionPolicy(
                workspace_id=self._context.workspace_id,
                version=1,
                strategy=legacy_strategy,
                effective_at=self._now(),
                retention_seconds=(
                    7 * 24 * 60 * 60
                    if legacy_strategy is RetentionStrategy.SCHEDULED
                    else None
                ),
                created_by=None,
            )
            self._session.add(policy)
            self._session.flush()
        existing = self._session.scalar(
            select(ManagedObject).where(
                ManagedObject.workspace_id == self._context.workspace_id,
                ManagedObject.owner_type == "import_batch_screenshot",
                ManagedObject.owner_id == batch.id,
            )
        )
        if existing is not None:
            return existing
        if policy.strategy is RetentionStrategy.EVIDENCE and not evidence_reason:
            evidence_reason = f"screenshot lifecycle: {event}"
        state = {
            RetentionStrategy.IMMEDIATE: ManagedObjectState.DELETED,
            RetentionStrategy.SCHEDULED: ManagedObjectState.SCHEDULED,
            RetentionStrategy.EVIDENCE: ManagedObjectState.EVIDENCE,
        }[policy.strategy]
        purge_at = (
            self._now() + timedelta(seconds=policy.retention_seconds or 0)
            if policy.strategy is RetentionStrategy.SCHEDULED
            else None
        )
        if policy.strategy is RetentionStrategy.IMMEDIATE:
            batch.screenshot_bytes = None
        record = ManagedObject(
            workspace_id=self._context.workspace_id,
            owner_type="import_batch_screenshot",
            owner_id=batch.id,
            object_key=None,
            managed_prefix="database:import_batches:screenshot_bytes",
            policy_version=policy.version,
            strategy=policy.strategy,
            state=state,
            purge_at=purge_at,
            evidence_reason=(evidence_reason[:240] if evidence_reason else None),
            related_resource_type="import_batch",
            related_resource_id=batch.id,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def register_managed_object(
        self,
        *,
        owner_type: str,
        owner_id: UUID,
        object_key: str,
        managed_prefix: str,
        purge_at: datetime,
        claim_token: str | None = None,
        lease_expires_at: datetime | None = None,
        business_referenced: bool = False,
    ) -> ManagedObject:
        required_root = f"workspaces/{self._context.workspace_id}/"
        if (
            not managed_prefix.startswith(required_root)
            or not object_key.startswith(managed_prefix)
            or ".." in object_key.split("/")
        ):
            raise ValueError("managed object key is outside workspace prefix")
        existing = self._session.scalar(
            select(ManagedObject).where(
                ManagedObject.object_key == object_key
            )
        )
        if existing is not None:
            if existing.workspace_id != self._context.workspace_id:
                raise LookupError("managed object not found")
            return existing
        policy = self.current_policy()
        record = ManagedObject(
            workspace_id=self._context.workspace_id,
            owner_type=owner_type,
            owner_id=owner_id,
            object_key=object_key,
            managed_prefix=managed_prefix,
            policy_version=policy.version if policy else 0,
            strategy=(
                policy.strategy if policy else RetentionStrategy.SCHEDULED
            ),
            state=(
                ManagedObjectState.REFERENCED
                if business_referenced
                else ManagedObjectState.ACTIVE
            ),
            purge_at=purge_at,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
        )
        self._session.add(record)
        self._session.flush()
        return record


class ManagedObjectCleaner:
    def __init__(
        self,
        session: Session,
        storage: Storage,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._now = now or (lambda: datetime.now(UTC))

    def cleanup_due(self, workspace_id: UUID) -> list[UUID]:
        current = self._now()
        records = list(
            self._session.scalars(
                select(ManagedObject)
                .where(
                    ManagedObject.workspace_id == workspace_id,
                    ManagedObject.state.in_(
                        [
                            ManagedObjectState.ACTIVE,
                            ManagedObjectState.SCHEDULED,
                            ManagedObjectState.RETRYING,
                        ]
                    ),
                    ManagedObject.purge_at.is_not(None),
                    ManagedObject.purge_at <= current,
                    or_(
                        ManagedObject.lease_expires_at.is_(None),
                        ManagedObject.lease_expires_at <= current,
                    ),
                )
                .order_by(ManagedObject.purge_at, ManagedObject.id)
            )
        )
        processed: list[UUID] = []
        for record in records:
            if self._is_in_use(record):
                continue
            try:
                self._delete(record)
                record.state = ManagedObjectState.DELETED
                record.error_code = None
            except Exception:
                record.state = ManagedObjectState.RETRYING
                record.attempt_count += 1
                record.error_code = "RETENTION_DELETE_FAILED"
            processed.append(record.id)
            self._session.flush()
        return processed

    def _is_in_use(self, record: ManagedObject) -> bool:
        if record.state is ManagedObjectState.REFERENCED:
            return True
        if record.owner_type == "restore_job":
            restore = self._session.get(RestoreJob, record.owner_id)
            if (
                restore is not None
                and (
                    restore.phase is FullRestorePhase.COMPENSATION_REQUIRED
                    or restore.status
                    in {
                        FullRestoreStatus.QUEUED,
                        FullRestoreStatus.RUNNING,
                        FullRestoreStatus.RETRYING,
                    }
                    or (
                        restore.claim_token is not None
                        and restore.lease_expires_at is not None
                        and restore.lease_expires_at > self._now()
                    )
                )
            ):
                return True
        if record.owner_type == "export_job":
            export = self._session.get(ExportTask, record.owner_id)
            if (
                export is not None
                and export.status is ExportStatus.RUNNING
                and export.claim_token is not None
                and export.lease_expires_at is not None
                and export.lease_expires_at > self._now()
            ):
                return True
        if record.object_key is None:
            return False
        key = record.object_key
        required_root = f"workspaces/{record.workspace_id}/"
        if (
            not record.managed_prefix.startswith(required_root)
            or not key.startswith(record.managed_prefix)
        ):
            return True
        if self._session.scalar(
            select(ContentAsset.id).where(
                ContentAsset.workspace_id == record.workspace_id,
                ContentAsset.object_key == key,
            )
        ):
            return True
        if self._session.scalar(
            select(RiskDocument.id).where(
                RiskDocument.workspace_id == record.workspace_id,
                RiskDocument.object_key == key,
            )
        ):
            return True
        if self._session.scalar(
            select(ExportTask.id).where(
                ExportTask.workspace_id == record.workspace_id,
                ExportTask.object_key == key,
            )
        ):
            return True
        return False

    def _delete(self, record: ManagedObject) -> None:
        if record.object_key is not None:
            self._storage.delete_object(record.object_key)
            return
        if record.owner_type != "import_batch_screenshot":
            raise RuntimeError("unknown database managed object")
        batch = self._session.scalar(
            select(ImportBatch).where(
                ImportBatch.id == record.owner_id,
                ImportBatch.workspace_id == record.workspace_id,
            )
        )
        if batch is not None:
            batch.screenshot_bytes = None


def purge_expired_trash(
    session: Session,
    workspace_id: UUID,
    *,
    now: Callable[[], datetime] | None = None,
) -> list[UUID]:
    current = (now or (lambda: datetime.now(UTC)))()
    items = list(
        session.scalars(
            select(DeletedItem)
            .where(
                DeletedItem.workspace_id == workspace_id,
                DeletedItem.status == DeletedItemStatus.RECOVERABLE,
                DeletedItem.scheduled_purge_at <= current,
            )
            .order_by(DeletedItem.scheduled_purge_at, DeletedItem.id)
        )
    )
    purged: list[UUID] = []
    for item in items:
        if item.resource_type != "content":
            continue
        content = session.scalar(
            select(Content).where(
                Content.id == item.resource_id,
                Content.workspace_id == workspace_id,
                Content.deleted_at.is_not(None),
            )
        )
        item.status = DeletedItemStatus.PURGING
        session.flush()
        if content is not None:
            session.delete(content)
            session.flush()
        item.status = DeletedItemStatus.PURGED
        session.add(
            DeletionAudit(
                workspace_id=workspace_id,
                actor_id=item.deleted_by,
                operation="content.purge",
                resource_type="content",
                resource_id=item.resource_id,
                phase="purged",
                status="succeeded",
                created_at=current,
            )
        )
        purged.append(item.id)
        session.flush()
    return purged


class TrashService:
    def __init__(
        self,
        session: Session,
        context: WorkspaceContext,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._context = context
        self._now = now or (lambda: datetime.now(UTC))

    def list_items(self) -> list[DeletedItem]:
        require_permission(self._context.role, Permission.READ_CONTENT)
        return list(
            self._session.scalars(
                select(DeletedItem)
                .where(
                    DeletedItem.workspace_id == self._context.workspace_id,
                    DeletedItem.status == DeletedItemStatus.RECOVERABLE,
                )
                .order_by(
                    DeletedItem.deleted_at.desc(),
                    DeletedItem.id,
                )
            )
        )

    def soft_delete_content(
        self,
        content_id: UUID,
        *,
        reason: str | None = None,
        failure_injector: Callable[[str], None] | None = None,
    ) -> DeletedItem:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        content = self._session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == self._context.workspace_id,
            )
        )
        if content is None:
            raise LookupError("content not found")
        existing = self._session.scalar(
            select(DeletedItem)
            .where(
                DeletedItem.workspace_id == self._context.workspace_id,
                DeletedItem.resource_type == "content",
                DeletedItem.resource_id == content_id,
                DeletedItem.status == DeletedItemStatus.RECOVERABLE,
            )
            .order_by(DeletedItem.deleted_at.desc())
        )
        if existing is not None:
            return existing
        current = self._now()
        content.deleted_at = current
        item = DeletedItem(
            workspace_id=self._context.workspace_id,
            resource_type="content",
            resource_id=content.id,
            deleted_by=self._context.member_id,
            deleted_at=current,
            scheduled_purge_at=current + DEFAULT_TRASH_RETENTION,
            deletion_reason=(reason[:240] if reason else None),
            status=DeletedItemStatus.RECOVERABLE,
        )
        self._session.add(item)
        self._session.flush()
        if failure_injector is not None:
            failure_injector("after_trash_record")
        self._audit("content.soft_deleted", content.id)
        self._session.flush()
        return item

    def restore_content(self, content_id: UUID) -> Content:
        require_permission(self._context.role, Permission.WRITE_CONTENT)
        content = self._session.scalar(
            select(Content).where(
                Content.id == content_id,
                Content.workspace_id == self._context.workspace_id,
            )
        )
        if content is None:
            raise LookupError("content not found")
        item = self._session.scalar(
            select(DeletedItem)
            .where(
                DeletedItem.workspace_id == self._context.workspace_id,
                DeletedItem.resource_type == "content",
                DeletedItem.resource_id == content_id,
            )
            .order_by(DeletedItem.deleted_at.desc())
        )
        if content.deleted_at is None:
            if item is not None and item.status is DeletedItemStatus.RESTORED:
                return content
            raise ValueError("content is not deleted")
        if item is None or item.status is not DeletedItemStatus.RECOVERABLE:
            raise ValueError("content is not recoverable")
        current = self._now()
        if item.scheduled_purge_at <= current:
            raise ResourcePurgeExpired("resource purge window expired")
        content.deleted_at = None
        item.status = DeletedItemStatus.RESTORED
        item.restored_at = current
        self._audit("content.restored", content.id)
        self._session.flush()
        return content

    def _audit(self, action: str, resource_id: UUID) -> None:
        self._session.add(
            AuditLog(
                workspace_id=self._context.workspace_id,
                member_id=self._context.member_id,
                action=action,
                resource_type="content",
                resource_id=resource_id,
            )
        )

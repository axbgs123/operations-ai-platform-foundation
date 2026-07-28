from dataclasses import dataclass
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from io import BytesIO
import json
import stat
import secrets
from typing import Any, cast
from uuid import UUID, uuid5
from zipfile import BadZipFile, LargeZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile

from sqlalchemy import and_, delete, inspect, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext, WorkspaceRole
from app.core.storage import Storage
from app.modules.content.models import ContentAsset
from app.modules.exports.models import (
    FullRestorePhase,
    FullRestoreStatus,
    KnowledgeIndexRebuild,
    KnowledgeIndexStatus,
    ManagedObject,
    ManagedObjectState,
    RestoreJob,
)
from app.modules.exports.restore_preview import (
    APPLY_ORDER,
    MODEL_BY_TYPE,
    RestoreAction,
    RestoreMode,
    RestorePreview,
    apply_lightweight_restore,
    build_restore_preview,
)
from app.modules.models.models import ModelConfig, ModelConfigStatus
from app.modules.models.config_service import model_configuration_version
from app.modules.models.catalog import get_catalog_entry
from app.modules.risk_rag.chunking import chunk_document
from app.modules.risk_rag.models import (
    RiskChunk,
    RiskDocument,
    RiskDocumentScope,
)
from app.modules.style_facts.fact_models import FactSource
from app.modules.workspace.models import Workspace
from app.modules.workspace.models import MemberRole, WorkspaceMember

from app.modules.exports.checksums import (
    parse_checksum_manifest,
    validate_archive_path,
    verify_checksums,
)
from app.modules.exports.manifest import (
    BACKUP_SCHEMA_VERSION,
    BackupFormatError,
    BackupManifest,
    canonical_manifest_json,
    parse_manifest_json,
)


@dataclass(frozen=True)
class ArchiveLimits:
    max_upload_bytes: int = 50 * 1024 * 1024
    max_files: int = 2_000
    max_file_bytes: int = 25 * 1024 * 1024
    max_total_bytes: int = 250 * 1024 * 1024
    max_compression_ratio: float = 100.0


class BackupArchiveError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class FullRestoreIdempotencyConflict(ValueError):
    pass


class RestoreClaimLost(RuntimeError):
    pass


RESTORE_LEASE_DURATION = timedelta(minutes=5)


@dataclass(frozen=True)
class VerifiedBackupArchive:
    manifest: BackupManifest
    files: dict[str, bytes]

    @property
    def assets(self) -> dict[str, bytes]:
        return {
            path: content
            for path, content in self.files.items()
            if path.startswith("assets/")
        }

    @property
    def knowledge(self) -> dict[str, bytes]:
        return {
            path: content
            for path, content in self.files.items()
            if path.startswith("knowledge/")
        }


def _unsafe(message: str) -> BackupArchiveError:
    return BackupArchiveError("BACKUP_ARCHIVE_UNSAFE", message)


def _validate_member_path(path: str) -> None:
    if path == "checksums.json":
        return
    try:
        validate_archive_path(path)
    except ValueError as error:
        raise _unsafe(f"unsafe archive path: {path[:160]}") from error


def read_verified_backup_zip(
    payload: bytes,
    *,
    limits: ArchiveLimits = ArchiveLimits(),
) -> VerifiedBackupArchive:
    if len(payload) > limits.max_upload_bytes:
        raise _unsafe("archive upload exceeds size limit")
    try:
        with ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_files:
                raise _unsafe("archive contains too many files")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)) or len(names) != len(
                {name.casefold() for name in names}
            ):
                raise _unsafe("archive contains duplicate paths")
            required = {"manifest.json", "data.json", "checksums.json"}
            if not required <= set(names):
                raise _unsafe("archive is missing a required root file")
            total_declared = 0
            for info in infos:
                _validate_member_path(info.filename)
                if info.is_dir() or info.filename.endswith("/"):
                    raise _unsafe("archive contains a special file")
                mode = info.external_attr >> 16
                file_type = stat.S_IFMT(mode)
                if file_type not in {0, stat.S_IFREG}:
                    raise _unsafe("archive contains a special file")
                if info.flag_bits & 0x1:
                    raise _unsafe("archive contains an encrypted file")
                if info.compress_type not in {ZIP_STORED, ZIP_DEFLATED}:
                    raise _unsafe("archive uses unsupported compression")
                if info.file_size > limits.max_file_bytes:
                    raise _unsafe(
                        f"archive member exceeds size limit: "
                        f"{info.filename[:160]}"
                    )
                total_declared += info.file_size
                if total_declared > limits.max_total_bytes:
                    raise _unsafe("archive exceeds total size limit")
                if info.file_size:
                    ratio = info.file_size / max(info.compress_size, 1)
                    if ratio > limits.max_compression_ratio:
                        raise _unsafe(
                            f"archive compression ratio is unsafe: "
                            f"{info.filename[:160]}"
                        )

            files: dict[str, bytes] = {}
            total_actual = 0
            for info in infos:
                chunks: list[bytes] = []
                actual = 0
                with archive.open(info, "r") as source:
                    while chunk := source.read(64 * 1024):
                        actual += len(chunk)
                        total_actual += len(chunk)
                        if actual > limits.max_file_bytes:
                            raise _unsafe(
                                f"archive member exceeds size limit: "
                                f"{info.filename[:160]}"
                            )
                        if total_actual > limits.max_total_bytes:
                            raise _unsafe("archive exceeds total size limit")
                        chunks.append(chunk)
                if actual != info.file_size:
                    raise _unsafe(
                        f"archive member size changed: {info.filename[:160]}"
                    )
                content = b"".join(chunks)
                if (
                    info.filename.lower().endswith(".zip")
                    or content.startswith(b"PK\x03\x04")
                ):
                    raise _unsafe(
                        f"nested archive is forbidden: {info.filename[:160]}"
                    )
                files[info.filename] = content
    except BackupArchiveError:
        raise
    except (BadZipFile, LargeZipFile, RuntimeError, EOFError) as error:
        raise _unsafe("archive is invalid or truncated") from error

    try:
        checksums = parse_checksum_manifest(files["checksums.json"])
        protected = {
            path: content
            for path, content in files.items()
            if path != "checksums.json"
        }
        verify_checksums(protected, checksums)
    except (KeyError, ValueError) as error:
        raise BackupArchiveError(
            "BACKUP_CHECKSUM_MISMATCH",
            "backup checksum verification failed",
        ) from error
    try:
        manifest = parse_manifest_json(files["manifest.json"])
        data_manifest = parse_manifest_json(files["data.json"])
    except BackupFormatError as error:
        raw_version = files.get("data.json", b"")
        code = (
            "BACKUP_SCHEMA_UNSUPPORTED"
            if (
                b'"schema_version"' in raw_version
                and BACKUP_SCHEMA_VERSION.encode() not in raw_version
            )
            else "BACKUP_REFERENCE_INVALID"
        )
        raise BackupArchiveError(
            code,
            "backup manifest contract is invalid",
        ) from error
    if canonical_manifest_json(manifest) != canonical_manifest_json(data_manifest):
        raise BackupArchiveError(
            "BACKUP_REFERENCE_INVALID",
            "manifest and data contracts do not match",
        )
    return VerifiedBackupArchive(manifest=manifest, files=files)


def create_full_restore_preview(
    session: Session,
    context: WorkspaceContext,
    payload: bytes,
    storage: Storage,
    *,
    mode: RestoreMode,
    idempotency_key: str,
) -> tuple[RestoreJob, bool]:
    if context.role != "admin" or context.member_id is None:
        raise PermissionError("admin role required")
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise ValueError("valid idempotency key is required")
    archive_sha256 = hashlib.sha256(payload).hexdigest()
    request_fingerprint = hashlib.sha256(
        json.dumps(
            {"archive_sha256": archive_sha256, "mode": mode.value},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    existing = session.scalar(
        select(RestoreJob).where(
            RestoreJob.workspace_id == context.workspace_id,
            RestoreJob.requested_by == context.member_id,
            RestoreJob.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise FullRestoreIdempotencyConflict(
                "idempotency key already used for another restore"
            )
        return existing, False

    archive = read_verified_backup_zip(payload)
    preview = build_restore_preview(
        session,
        context,
        archive.manifest,
        mode=mode,
        idempotency_key=idempotency_key,
    )
    if preview.target_workspace_id is None:
        raise ValueError("restore preview has no target workspace")
    job = RestoreJob(
        workspace_id=context.workspace_id,
        requested_by=context.member_id,
        target_workspace_id=preview.target_workspace_id,
        mode=mode.value,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        archive_sha256=archive_sha256,
        archive_object_key="pending",
        staging_prefix="pending",
        status=FullRestoreStatus.QUEUED,
        phase=FullRestorePhase.PREVIEW_READY,
        preview_id=preview.preview_id,
        manifest_fingerprint=preview.manifest_fingerprint,
        preview_json=preview.model_dump(mode="json"),
        object_plan=[],
    )
    staged_keys: list[str] = []
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
        staging_prefix = (
            f"workspaces/{context.workspace_id}/restore-staging/{job.id}"
        )
        archive_key = f"{staging_prefix}/archive.zip"
        storage.put_object(
            archive_key,
            payload,
            mime_type="application/zip",
        )
        staged_keys.append(archive_key)
        plan = _build_object_plan(
            session,
            archive,
            storage,
            preview.target_workspace_id,
            staging_prefix,
        )
        for item in plan:
            path = str(item["archive_path"])
            staging_key = str(item["staging_key"])
            storage.put_object(
                staging_key,
                archive.files[path],
                mime_type=str(item["mime_type"]),
            )
            staged_keys.append(staging_key)
        job.archive_object_key = archive_key
        job.staging_prefix = staging_prefix
        job.object_plan = plan
        from app.modules.exports.deletion import RetentionService

        retention = RetentionService(session, context)
        purge_at = datetime.now(UTC) + timedelta(minutes=15)
        for object_key in staged_keys:
            retention.register_managed_object(
                owner_type="restore_job",
                owner_id=job.id,
                object_key=object_key,
                managed_prefix=f"{staging_prefix}/",
                purge_at=purge_at,
            )
        session.flush()
    except IntegrityError:
        for object_key in staged_keys:
            _safe_delete(storage, object_key)
        existing = session.scalar(
            select(RestoreJob).where(
                RestoreJob.workspace_id == context.workspace_id,
                RestoreJob.requested_by == context.member_id,
                RestoreJob.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        if existing.request_fingerprint != request_fingerprint:
            raise FullRestoreIdempotencyConflict(
                "idempotency key already used for another restore"
            )
        return existing, False
    except Exception:
        for object_key in staged_keys:
            _safe_delete(storage, object_key)
        session.rollback()
        persisted = session.get(RestoreJob, job.id)
        if persisted is not None:
            session.delete(persisted)
            session.commit()
        raise
    return job, True


def confirm_full_restore(
    session: Session,
    context: WorkspaceContext,
    job_id,
    *,
    preview_id: str,
    manifest_fingerprint: str,
    idempotency_key: str,
    storage: Storage,
    failure_injector: Callable[[str, int], None] | None = None,
    claim_token: str | None = None,
) -> RestoreJob:
    if context.role != "admin":
        raise PermissionError("admin role required")
    if not idempotency_key.strip() or len(idempotency_key) > 200:
        raise ValueError("valid idempotency key is required")
    job = session.scalar(
        select(RestoreJob).where(
            RestoreJob.id == job_id,
            RestoreJob.workspace_id == context.workspace_id,
        )
    )
    if job is None:
        raise LookupError("restore job not found")
    if claim_token is not None:
        _assert_restore_claim(session, job.id, claim_token)
    if job.status is FullRestoreStatus.SUCCEEDED:
        if job.confirm_idempotency_key != idempotency_key:
            raise FullRestoreIdempotencyConflict(
                "restore already confirmed with another key"
            )
        return job
    if (
        job.confirm_idempotency_key is not None
        and job.confirm_idempotency_key != idempotency_key
    ):
        raise FullRestoreIdempotencyConflict(
            "confirmation idempotency conflict"
        )
    if (
        job.preview_id != preview_id
        or job.manifest_fingerprint != manifest_fingerprint
    ):
        raise ValueError("restore preview is stale")
    payload = storage.get_object(job.archive_object_key)
    if not hmac.compare_digest(
        hashlib.sha256(payload).hexdigest(),
        job.archive_sha256,
    ):
        raise ValueError("restore preview is stale")
    archive = read_verified_backup_zip(payload)
    preview = RestorePreview.model_validate(job.preview_json)
    if preview.preview_id != preview_id:
        raise ValueError("restore preview is stale")
    job.confirm_idempotency_key = idempotency_key
    job.status = FullRestoreStatus.RUNNING
    job.phase = FullRestorePhase.DATABASE
    job.error_code = None
    session.commit()
    if claim_token is not None:
        _renew_restore_claim(session, job.id, claim_token)

    compensation = _capture_compensation(session, preview, job)
    try:
        if claim_token is not None:
            _assert_restore_claim(session, job.id, claim_token)
        apply_lightweight_restore(
            session,
            context,
            archive.manifest,
            preview,
        )
        _apply_full_file_records(
            session,
            archive,
            job,
            compensation,
        )
        if failure_injector is not None:
            failure_injector("database_write", 1)
        if claim_token is not None:
            _assert_restore_claim(session, job.id, claim_token)
        session.commit()
    except Exception:
        session.rollback()
        _mark_restore_failed(
            session,
            job.id,
            "RESTORE_DATABASE_FAILED",
            claim_token=claim_token,
        )
        raise

    job = session.get(RestoreJob, job.id)
    assert job is not None
    if claim_token is not None:
        _renew_restore_claim(session, job.id, claim_token)
    job.phase = FullRestorePhase.MOVING_OBJECTS
    session.commit()
    copied: list[str] = []
    try:
        if claim_token is not None:
            _assert_restore_claim(session, job.id, claim_token)
        for index, item in enumerate(job.object_plan, start=1):
            if bool(item.get("skip_existing")):
                continue
            if claim_token is not None:
                _assert_restore_claim(session, job.id, claim_token)
            if failure_injector is not None:
                failure_injector("move_object", index)
            staging_key = str(item["staging_key"])
            final_key = str(item["final_key"])
            existing = storage.inspect_object(final_key)
            if existing is not None:
                raise RuntimeError("restore target object already exists")
            content = storage.get_object(staging_key)
            storage.put_object(
                final_key,
                content,
                mime_type=str(item["mime_type"]),
            )
            copied.append(final_key)
            if claim_token is not None:
                _assert_restore_claim(session, job.id, claim_token)
    except Exception:
        for final_key in reversed(copied):
            _safe_delete(storage, final_key)
        try:
            if failure_injector is not None:
                failure_injector("compensate_database", 1)
            _compensate_database(session, preview, compensation)
            _mark_restore_failed(
                session,
                job.id,
                "RESTORE_OBJECT_MOVE_FAILED",
                claim_token=claim_token,
            )
        except Exception:
            session.rollback()
            failed = session.get(RestoreJob, job.id)
            if failed is not None:
                failed.status = FullRestoreStatus.FAILED
                failed.phase = FullRestorePhase.COMPENSATION_REQUIRED
                failed.error_code = "RESTORE_COMPENSATION_REQUIRED"
                session.commit()
        raise

    for item in job.object_plan:
        _safe_delete(storage, str(item["staging_key"]))
    _safe_delete(storage, job.archive_object_key)
    for managed_object in session.scalars(
        select(ManagedObject).where(
            ManagedObject.workspace_id == job.workspace_id,
            ManagedObject.owner_type == "restore_job",
            ManagedObject.owner_id == job.id,
        )
    ):
        managed_object.state = ManagedObjectState.DELETED
        managed_object.error_code = None
    if claim_token is not None:
        _renew_restore_claim(session, job.id, claim_token)
    job.phase = FullRestorePhase.REBUILDING_INDEX
    session.commit()
    _rebuild_knowledge_indexes(session, context, archive, job)
    job = session.get(RestoreJob, job.id)
    assert job is not None
    if claim_token is not None:
        _assert_restore_claim(session, job.id, claim_token)
    job.status = FullRestoreStatus.SUCCEEDED
    job.phase = FullRestorePhase.COMPLETED
    job.error_code = None
    job.completed_at = datetime.now(UTC)
    job.claim_token = None
    job.lease_expires_at = None
    session.commit()
    return job


def process_full_restore_task(
    session: Session,
    job_id: UUID,
    storage: Storage,
) -> None:
    now = datetime.now(UTC)
    claim_token = secrets.token_hex(16)
    claimed = session.execute(
        update(RestoreJob)
        .where(
            RestoreJob.id == job_id,
            or_(
                RestoreJob.status.in_(
                    [
                        FullRestoreStatus.QUEUED,
                        FullRestoreStatus.RETRYING,
                    ]
                ),
                and_(
                    RestoreJob.status == FullRestoreStatus.RUNNING,
                    RestoreJob.lease_expires_at.is_not(None),
                    RestoreJob.lease_expires_at <= now,
                ),
            ),
        )
        .values(
            status=FullRestoreStatus.RUNNING,
            claim_token=claim_token,
            lease_expires_at=now + RESTORE_LEASE_DURATION,
        )
    )
    if getattr(claimed, "rowcount", 0) != 1:
        session.rollback()
        return
    session.commit()
    job = session.get(RestoreJob, job_id)
    if job is None:
        return
    member = session.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.id == job.requested_by,
            WorkspaceMember.workspace_id == job.workspace_id,
            WorkspaceMember.revoked_at.is_(None),
        )
    )
    if member is None or member.role is not MemberRole.ADMIN:
        _mark_restore_failed(
            session,
            job.id,
            "RESTORE_AUTHORIZATION_REVOKED",
            claim_token=claim_token,
        )
        return
    if job.confirm_idempotency_key is None:
        _mark_restore_failed(
            session,
            job.id,
            "RESTORE_CONFIRMATION_REQUIRED",
            claim_token=claim_token,
        )
        return
    context = WorkspaceContext(
        workspace_id=job.workspace_id,
        member_id=member.id,
        role=cast(WorkspaceRole, member.role.value),
    )
    try:
        confirm_full_restore(
            session,
            context,
            job.id,
            preview_id=job.preview_id,
            manifest_fingerprint=job.manifest_fingerprint,
            idempotency_key=job.confirm_idempotency_key,
            storage=storage,
            claim_token=claim_token,
        )
    except Exception:
        session.rollback()


def _target_record_id(
    target_workspace_id: UUID,
    source_workspace_id: UUID,
    record_type: str,
    source_id: UUID,
) -> UUID:
    if target_workspace_id == source_workspace_id:
        return source_id
    return uuid5(target_workspace_id, f"{record_type}:{source_id}")


def _source_id_from_file_name(path: str) -> UUID:
    return UUID(path.rsplit("/", 1)[-1][:36])


def _build_object_plan(
    session: Session,
    archive: VerifiedBackupArchive,
    storage: Storage,
    target_workspace_id: UUID,
    staging_prefix: str,
) -> list[dict[str, object]]:
    records = {
        (record.record_type.value, record.source_id): record
        for record in archive.manifest.records
    }
    plan: list[dict[str, object]] = []
    for path in sorted((*archive.assets, *archive.knowledge)):
        if path.startswith("assets/"):
            kind = "asset_reference"
            source_id = _source_id_from_file_name(path)
            record = records[(kind, source_id)]
            mime_type = str(record.data["mime_type"])
        elif path.startswith("knowledge/facts/"):
            kind = "fact_source_metadata"
            source_id = _source_id_from_file_name(path)
            record = records[(kind, source_id)]
            mime_type = str(record.data.get("mime_type") or "application/octet-stream")
        else:
            kind = "risk_document_metadata"
            source_id = _source_id_from_file_name(path)
            record = records[(kind, source_id)]
            mime_type = str(record.data.get("mime_type") or "application/octet-stream")
        target_id = _target_record_id(
            target_workspace_id,
            archive.manifest.workspace.source_id,
            kind,
            source_id,
        )
        existing: Any
        skip_existing = False
        content = archive.files[path]
        if kind == "asset_reference":
            existing = session.get(ContentAsset, target_id)
            skip_existing = (
                existing is not None
                and existing.workspace_id == target_workspace_id
                and storage.inspect_object(existing.object_key) is not None
                and storage.get_object(existing.object_key) == content
            )
        elif kind == "fact_source_metadata":
            existing = session.get(FactSource, target_id)
            skip_existing = (
                existing is not None
                and existing.workspace_id == target_workspace_id
                and existing.raw_content == content
            )
        else:
            existing = session.get(RiskDocument, target_id)
            skip_existing = (
                existing is not None
                and existing.workspace_id == target_workspace_id
                and existing.object_key is not None
                and storage.inspect_object(existing.object_key) is not None
                and storage.get_object(existing.object_key) == content
            )
        safe_leaf = path.rsplit("/", 1)[-1]
        plan.append(
            {
                "archive_path": path,
                "record_type": kind,
                "source_id": str(source_id),
                "target_id": str(target_id),
                "staging_key": f"{staging_prefix}/files/{path}",
                "final_key": (
                    f"workspaces/{target_workspace_id}/restored/"
                    f"{kind}/{target_id}/{safe_leaf}"
                ),
                "mime_type": mime_type,
                "skip_existing": skip_existing,
            }
        )
    return plan


@dataclass
class _CompensationState:
    created: list[tuple[Any, UUID]]
    overwritten: list[tuple[Any, UUID, dict[str, Any]]]
    new_workspace: bool


def _capture_columns(instance: Any) -> dict[str, Any]:
    return {
        attribute.key: deepcopy(getattr(instance, attribute.key))
        for attribute in inspect(instance).mapper.column_attrs
    }


def _capture_compensation(
    session: Session,
    preview: RestorePreview,
    job: RestoreJob,
) -> _CompensationState:
    created: list[tuple[Any, UUID]] = []
    overwritten: list[tuple[Any, UUID, dict[str, Any]]] = []
    for item in preview.items:
        if item.target_id is None or item.record_type.value == "asset_reference":
            continue
        model = MODEL_BY_TYPE[item.record_type]
        if item.action is RestoreAction.CREATE:
            created.append((model, item.target_id))
        elif item.action is RestoreAction.OVERWRITE:
            existing = session.get(cast(Any, model), item.target_id)
            if existing is None:
                raise ValueError("restore preview is stale")
            overwritten.append(
                (model, item.target_id, _capture_columns(existing))
            )
    captured = {(model, target_id) for model, target_id, _ in overwritten}
    file_model_by_type = {
        "asset_reference": ContentAsset,
        "fact_source_metadata": FactSource,
        "risk_document_metadata": RiskDocument,
    }
    for object_item in job.object_plan:
        if bool(object_item.get("skip_existing")):
            continue
        model = file_model_by_type[str(object_item["record_type"])]
        target_id = UUID(str(object_item["target_id"]))
        existing = session.get(cast(Any, model), target_id)
        if existing is not None and (model, target_id) not in captured:
            overwritten.append(
                (model, target_id, _capture_columns(existing))
            )
            captured.add((model, target_id))
    return _CompensationState(
        created=created,
        overwritten=overwritten,
        new_workspace=preview.mode is RestoreMode.NEW,
    )


def _apply_full_file_records(
    session: Session,
    archive: VerifiedBackupArchive,
    job: RestoreJob,
    compensation: _CompensationState,
) -> None:
    records = {
        (record.record_type.value, record.source_id): record
        for record in archive.manifest.records
    }
    for item in job.object_plan:
        if bool(item.get("skip_existing")):
            continue
        record_type = str(item["record_type"])
        source_id = UUID(str(item["source_id"]))
        target_id = UUID(str(item["target_id"]))
        record = records[(record_type, source_id)]
        if record_type == "asset_reference":
            existing_asset = session.get(ContentAsset, target_id)
            content_id = _target_record_id(
                job.target_workspace_id,
                archive.manifest.workspace.source_id,
                "content",
                UUID(str(record.data["content_id"])),
            )
            if existing_asset is None:
                asset = ContentAsset(
                    workspace_id=job.target_workspace_id,
                    content_id=content_id,
                    category=record.data["category"],
                    object_key=str(item["final_key"]),
                    file_name=str(record.data["file_name"]),
                    mime_type=str(record.data["mime_type"]),
                    size=int(record.data["size"]),
                )
                asset.id = target_id
                session.add(asset)
                compensation.created.append((ContentAsset, target_id))
            else:
                existing_asset.content_id = content_id
                existing_asset.category = record.data["category"]
                existing_asset.object_key = str(item["final_key"])
                existing_asset.file_name = str(record.data["file_name"])
                existing_asset.mime_type = str(record.data["mime_type"])
                existing_asset.size = int(record.data["size"])
        elif record_type == "fact_source_metadata":
            source = session.get(FactSource, target_id)
            if source is None:
                raise ValueError("restored fact source is missing")
            content = archive.files[str(item["archive_path"])]
            source.raw_content = content
            source.content_sha256 = hashlib.sha256(content).hexdigest()
        elif record_type == "risk_document_metadata":
            document = session.get(RiskDocument, target_id)
            if document is None:
                raise ValueError("restored risk document is missing")
            document.object_key = str(item["final_key"])
            content = archive.files[str(item["archive_path"])]
            document.content_sha256 = hashlib.sha256(content).hexdigest()
    session.flush()


def _compensate_database(
    session: Session,
    preview: RestorePreview,
    compensation: _CompensationState,
) -> None:
    session.rollback()
    if compensation.new_workspace:
        target = session.get(Workspace, preview.target_workspace_id)
        if target is not None:
            session.delete(target)
        session.commit()
        return
    order_by_model = {
        model: APPLY_ORDER[record_type]
        for record_type, model in MODEL_BY_TYPE.items()
    }
    order_by_model[ContentAsset] = APPLY_ORDER[
        next(
            record_type
            for record_type in APPLY_ORDER
            if record_type.value == "asset_reference"
        )
    ]
    for model, target_id in sorted(
        compensation.created,
        key=lambda item: order_by_model.get(item[0], 99),
        reverse=True,
    ):
        instance = session.get(model, target_id)
        if instance is not None:
            session.delete(instance)
    session.flush()
    for model, target_id, values in compensation.overwritten:
        instance = session.get(model, target_id)
        if instance is None:
            raise RuntimeError("restore compensation target is missing")
        for key, value in values.items():
            setattr(instance, key, deepcopy(value))
    session.commit()


def _mark_restore_failed(
    session: Session,
    job_id: UUID,
    error_code: str,
    *,
    claim_token: str | None = None,
) -> None:
    session.rollback()
    conditions = [RestoreJob.id == job_id]
    if claim_token is not None:
        conditions.append(RestoreJob.claim_token == claim_token)
    session.execute(
        update(RestoreJob)
        .where(*conditions)
        .values(
            status=FullRestoreStatus.FAILED,
            phase=FullRestorePhase.FAILED,
            error_code=error_code,
            claim_token=None,
            lease_expires_at=None,
        )
    )
    session.commit()


def _assert_restore_claim(
    session: Session,
    job_id: UUID,
    claim_token: str,
) -> None:
    current = session.scalar(
        select(RestoreJob.claim_token).where(
            RestoreJob.id == job_id,
            RestoreJob.status == FullRestoreStatus.RUNNING,
        )
    )
    if current != claim_token:
        raise RestoreClaimLost("restore worker claim is no longer current")


def _renew_restore_claim(
    session: Session,
    job_id: UUID,
    claim_token: str,
) -> None:
    result = session.execute(
        update(RestoreJob)
        .where(
            RestoreJob.id == job_id,
            RestoreJob.status == FullRestoreStatus.RUNNING,
            RestoreJob.claim_token == claim_token,
        )
        .values(
            lease_expires_at=datetime.now(UTC) + RESTORE_LEASE_DURATION
        )
    )
    if getattr(result, "rowcount", 0) != 1:
        session.rollback()
        raise RestoreClaimLost("restore worker claim is no longer current")
    session.commit()


def _safe_delete(storage: Storage, object_key: str) -> bool:
    try:
        storage.delete_object(object_key)
    except Exception:
        return False
    return True


def _rebuild_knowledge_indexes(
    session: Session,
    _source_context: WorkspaceContext,
    archive: VerifiedBackupArchive,
    job: RestoreJob,
) -> None:
    documents: list[tuple[RiskDocument, bytes]] = []
    for item in job.object_plan:
        if item["record_type"] != "risk_document_metadata":
            continue
        if bool(item.get("skip_existing")):
            continue
        document = session.get(RiskDocument, UUID(str(item["target_id"])))
        if document is None:
            continue
        documents.append(
            (document, archive.files[str(item["archive_path"])])
        )
    platforms = sorted({document.platform for document, _ in documents})
    if not platforms:
        job.knowledge_index_message = None
        session.commit()
        return
    configs = list(
        session.scalars(
            select(ModelConfig)
            .where(
                ModelConfig.workspace_id == job.target_workspace_id,
                ModelConfig.status != ModelConfigStatus.INCOMPATIBLE,
            )
            .order_by(ModelConfig.provider, ModelConfig.model_id)
        )
    )
    config = next(
        (item for item in configs if "embedding" in item.capabilities),
        None,
    )
    if config is None or "embedding" not in config.capabilities:
        for platform in platforms:
            session.add(
                KnowledgeIndexRebuild(
                    workspace_id=job.target_workspace_id,
                    platform=platform,
                    status=KnowledgeIndexStatus.CONFIGURATION_REQUIRED,
                    index_generation=secrets.token_hex(16),
                    idempotency_key=f"restore:{job.id}:{platform.value}",
                    restore_job_id=job.id,
                    error_code="MODEL_CONFIGURATION_REQUIRED",
                )
            )
        job.knowledge_index_message = "知识索引重建中"
        session.commit()
        return
    if config.provider == "mock":
        model_id = config.model_id
        contract_version = "mock-risk-embedding-v1"
        dimension = 4
        region = None
    else:
        try:
            catalog = get_catalog_entry(config.provider, config.model_id)
        except LookupError:
            catalog = None
        if (
            catalog is None
            or catalog.embedding_dimension is None
            or "embedding" not in config.capabilities
        ):
            for platform in platforms:
                session.add(
                    KnowledgeIndexRebuild(
                        workspace_id=job.target_workspace_id,
                        platform=platform,
                        status=KnowledgeIndexStatus.CONFIGURATION_REQUIRED,
                        index_generation=secrets.token_hex(16),
                        idempotency_key=f"restore:{job.id}:{platform.value}",
                        restore_job_id=job.id,
                        error_code="MODEL_CONFIGURATION_REQUIRED",
                    )
                )
            job.knowledge_index_message = "知识索引重建中"
            session.commit()
            return
        model_id = config.model_id
        contract_version = catalog.contract_version
        dimension = catalog.embedding_dimension
        region = config.region
    config_version = model_configuration_version(config)
    for platform in platforms:
        rebuild = KnowledgeIndexRebuild(
            workspace_id=job.target_workspace_id,
            platform=platform,
            status=KnowledgeIndexStatus.QUEUED,
            index_generation=secrets.token_hex(16),
            idempotency_key=f"restore:{job.id}:{platform.value}",
            restore_job_id=job.id,
            model_id=model_id,
            model_config_id=config.id,
            provider=config.provider,
            region=region,
            contract_version=contract_version,
            config_version=config_version,
            embedding_version=contract_version,
            dimension=dimension,
        )
        session.add(rebuild)
        session.flush()
        rebuild.index_generation = str(rebuild.id)
        platform_documents = [
            (document, content)
            for document, content in documents
            if document.platform is platform
        ]
        for document, content in platform_documents:
            session.execute(
                delete(RiskChunk).where(
                    RiskChunk.document_id == document.id
                )
            )
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                rebuild.status = KnowledgeIndexStatus.FAILED
                rebuild.error_code = "KNOWLEDGE_INDEX_SOURCE_INVALID"
                continue
            session.add_all(
                [
                    RiskChunk(
                        workspace_id=job.target_workspace_id,
                        document_id=document.id,
                        platform=platform,
                        scope=RiskDocumentScope.PRIVATE,
                        chunk_index=draft.chunk_index,
                        source_location=draft.source_location,
                        text=draft.text,
                        metadata_json={"untrusted_data": True},
                    )
                    for draft in chunk_document(text)
                ]
            )
    job.knowledge_index_message = "知识索引重建中"
    session.commit()

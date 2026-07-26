from datetime import UTC, datetime
from io import BytesIO
import json
from pathlib import PurePosixPath
import re
from zipfile import ZIP_STORED, ZipFile, ZipInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import WorkspaceContext
from app.core.storage import Storage
from app.modules.content.models import ContentAsset
from app.modules.exports.checksums import build_checksum_manifest
from app.modules.exports.json_backup import build_lightweight_manifest
from app.modules.exports.manifest import canonical_manifest_json
from app.modules.risk_rag.models import (
    RiskDocument,
    RiskDocumentScope,
)
from app.modules.style_facts.fact_models import FactSource


_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _safe_name(value: str | None, fallback: str) -> str:
    name = PurePosixPath((value or fallback).replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned[:180] or fallback


def _read_workspace_object(
    storage: Storage,
    workspace_id,
    object_key: str,
) -> bytes:
    required_prefix = f"workspaces/{workspace_id}/"
    if not object_key.startswith(required_prefix):
        raise ValueError("backup object is outside the workspace")
    return storage.get_object(object_key)


def _zip_info(path: str) -> ZipInfo:
    info = ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    info.compress_type = ZIP_STORED
    info.create_system = 3
    info.external_attr = 0o100600 << 16
    return info


def build_full_backup_zip(
    session: Session,
    context: WorkspaceContext,
    storage: Storage,
    *,
    exported_at: datetime | None = None,
) -> bytes:
    timestamp = exported_at or datetime.now(UTC)
    manifest = build_lightweight_manifest(
        session,
        context,
        exported_at=timestamp,
    )
    data_json = canonical_manifest_json(manifest)
    protected: dict[str, bytes] = {
        "manifest.json": data_json,
        "data.json": data_json,
    }
    for asset in session.scalars(
        select(ContentAsset)
        .where(ContentAsset.workspace_id == context.workspace_id)
        .order_by(ContentAsset.id)
    ):
        path = (
            f"assets/{asset.content_id}/{asset.id}-"
            f"{_safe_name(asset.file_name, 'asset.bin')}"
        )
        protected[path] = _read_workspace_object(
            storage,
            context.workspace_id,
            asset.object_key,
        )
    for source in session.scalars(
        select(FactSource)
        .where(
            FactSource.workspace_id == context.workspace_id,
            FactSource.raw_content.is_not(None),
        )
        .order_by(FactSource.id)
    ):
        if source.raw_content is None:
            continue
        path = (
            f"knowledge/facts/{source.id}-"
            f"{_safe_name(source.file_name, 'source.bin')}"
        )
        protected[path] = source.raw_content
    for document in session.scalars(
        select(RiskDocument)
        .where(
            RiskDocument.workspace_id == context.workspace_id,
            RiskDocument.scope == RiskDocumentScope.PRIVATE,
            RiskDocument.redistribution_authorized.is_(True),
            RiskDocument.object_key.is_not(None),
        )
        .order_by(RiskDocument.platform, RiskDocument.id)
    ):
        if document.object_key is None:
            continue
        path = (
            f"knowledge/risk/{document.platform.value}/{document.id}-"
            f"{_safe_name(document.file_name, 'document.bin')}"
        )
        protected[path] = _read_workspace_object(
            storage,
            context.workspace_id,
            document.object_key,
        )
    final_manifest = build_lightweight_manifest(
        session,
        context,
        exported_at=timestamp,
    )
    if canonical_manifest_json(final_manifest) != data_json:
        raise RuntimeError("workspace changed during full backup")
    checksums = build_checksum_manifest(protected)
    checksum_json = json.dumps(
        checksums.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    ordered_paths = [
        "manifest.json",
        "data.json",
        "checksums.json",
        *sorted(path for path in protected if path.startswith("assets/")),
        *sorted(path for path in protected if path.startswith("knowledge/")),
    ]
    all_files = {**protected, "checksums.json": checksum_json}
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for path in ordered_paths:
            archive.writestr(_zip_info(path), all_files[path])
    return output.getvalue()

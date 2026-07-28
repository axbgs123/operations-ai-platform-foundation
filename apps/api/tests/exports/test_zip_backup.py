import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID
from zipfile import ZipFile

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import StoredObject
from app.core.storage import get_storage
from app.main import app
from app.modules.content.models import ContentAsset
from app.modules.exports.checksums import ChecksumManifest
from app.modules.exports.models import ExportStatus, ExportTask
from app.modules.exports.router import get_export_enqueuer
from app.modules.exports.service import process_export_task
from app.modules.exports.zip_backup import build_full_backup_zip
from app.modules.risk_rag.models import RiskDocument
from app.modules.workspace.auth import InviteAuthService
from tests.exports.test_csv import _login_role
from tests.exports.test_json_backup import _seed_portable_workspace
from tests.imports.helpers import configured_client


EXPORTED_AT = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


class MemoryFullBackupStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.now = EXPORTED_AT

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

    def inspect_object(self, object_key: str) -> StoredObject | None:
        stored = self.objects.get(object_key)
        if stored is None:
            return None
        return StoredObject(size=len(stored[0]), mime_type=stored[1])

    def presign_download(self, object_key: str) -> tuple[str, datetime]:
        return (
            f"https://storage.test/download/{object_key}?expires=300",
            self.now + timedelta(minutes=5),
        )


def _context(client, engine, workspace_id: str):
    token = client.cookies.get("session")
    assert token is not None
    with Session(engine) as session:
        context = InviteAuthService(session).authenticate(token)
        assert context is not None
        assert context.workspace_id == UUID(workspace_id)
        return context


def test_full_backup_has_fixed_deterministic_layout_and_checksums() -> None:
    storage = MemoryFullBackupStorage()
    with configured_client() as (client, engine):
        workspace_id, _, _, _ = _seed_portable_workspace(client, engine)
        with Session(engine) as session:
            asset = session.scalar(
                select(ContentAsset).where(
                    ContentAsset.workspace_id == UUID(workspace_id)
                )
            )
            risk_document = session.scalar(
                select(RiskDocument).where(
                    RiskDocument.workspace_id == UUID(workspace_id)
                )
            )
            assert asset is not None
            assert risk_document is not None
            asset.object_key = (
                f"workspaces/{workspace_id}/assets/synthetic-cover.png"
            )
            risk_document.object_key = (
                f"workspaces/{workspace_id}/risk/synthetic-rule.txt"
            )
            risk_document.file_name = "synthetic-rule.txt"
            risk_document.mime_type = "text/plain"
            risk_document.redistribution_authorized = True
            session.commit()
            asset_key = asset.object_key
            risk_key = risk_document.object_key

        storage.put_object(asset_key, b"synthetic-image", mime_type="image/png")
        storage.put_object(
            risk_key,
            b"synthetic authorized knowledge",
            mime_type="text/plain",
        )
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            first = build_full_backup_zip(
                session,
                context,
                storage,
                exported_at=EXPORTED_AT,
            )
            second = build_full_backup_zip(
                session,
                context,
                storage,
                exported_at=EXPORTED_AT,
            )

        assert first == second
        with ZipFile(BytesIO(first)) as archive:
            names = archive.namelist()
            assert names[:3] == [
                "manifest.json",
                "data.json",
                "checksums.json",
            ]
            assert names[3:] == sorted(names[3:])
            assert len([name for name in names if name.startswith("assets/")]) == 1
            assert (
                len(
                    [
                        name
                        for name in names
                        if name.startswith("knowledge/")
                    ]
                )
                == 2
            )
            assert archive.read("manifest.json") == archive.read("data.json")
            checksums = ChecksumManifest.model_validate_json(
                archive.read("checksums.json")
            )
            protected = {entry.path for entry in checksums.files}
            assert protected == set(names) - {"checksums.json"}
            assert all(entry.byte_count > 0 for entry in checksums.files)


def test_full_backup_rejects_missing_or_cross_workspace_objects() -> None:
    storage = MemoryFullBackupStorage()
    with configured_client() as (client, engine):
        workspace_id, _, _, _ = _seed_portable_workspace(client, engine)
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            asset = session.scalar(
                select(ContentAsset).where(
                    ContentAsset.workspace_id == UUID(workspace_id)
                )
            )
            assert asset is not None
            asset.object_key = "workspaces/another-workspace/private.png"
            session.commit()
        with Session(engine) as session:
            with pytest.raises(ValueError, match="workspace"):
                build_full_backup_zip(session, context, storage)

        with Session(engine) as session:
            asset = session.scalar(
                select(ContentAsset).where(
                    ContentAsset.workspace_id == UUID(workspace_id)
                )
            )
            assert asset is not None
            asset.object_key = f"workspaces/{workspace_id}/missing.png"
            session.commit()
        with Session(engine) as session:
            with pytest.raises(FileNotFoundError):
                build_full_backup_zip(session, context, storage)


def test_full_backup_never_serializes_credentials_vectors_or_object_keys() -> None:
    storage = MemoryFullBackupStorage()
    with configured_client() as (client, engine):
        workspace_id, _, _, _ = _seed_portable_workspace(client, engine)
        with Session(engine) as session:
            asset = session.scalar(
                select(ContentAsset).where(
                    ContentAsset.workspace_id == UUID(workspace_id)
                )
            )
            assert asset is not None
            asset.object_key = f"workspaces/{workspace_id}/safe.png"
            session.commit()
        storage.put_object(
            f"workspaces/{workspace_id}/safe.png",
            b"synthetic-image",
            mime_type="image/png",
        )
        context = _context(client, engine, workspace_id)
        with Session(engine) as session:
            payload = build_full_backup_zip(session, context, storage)
        with ZipFile(BytesIO(payload)) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            serialized_metadata = json.dumps(manifest).lower()
        for forbidden in (
            "encrypted_api_key",
            "provider_workspace_id",
            '"authorization":',
            "cookie",
            "invite",
            "object_key",
            "session_token",
            "token_hash",
            "vector",
            "embedding",
            "signature=",
        ):
            assert forbidden not in serialized_metadata


def test_zip_export_reuses_async_idempotency_and_permissions() -> None:
    queued: list[UUID] = []
    storage = MemoryFullBackupStorage()
    with configured_client() as (admin, engine):
        app.dependency_overrides[get_storage] = lambda: storage
        app.dependency_overrides[get_export_enqueuer] = lambda: queued.append
        workspace_id, csrf, _, _ = _seed_portable_workspace(admin, engine)
        with Session(engine) as session:
            asset = session.scalar(
                select(ContentAsset).where(
                    ContentAsset.workspace_id == UUID(workspace_id)
                )
            )
            assert asset is not None
            asset.object_key = f"workspaces/{workspace_id}/source/cover.png"
            session.commit()
        storage.put_object(
            f"workspaces/{workspace_id}/source/cover.png",
            b"synthetic-cover",
            mime_type="image/png",
        )
        headers = {
            "X-CSRF-Token": csrf,
            "Idempotency-Key": "full-backup-1",
        }
        created = admin.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "zip"},
        )
        repeated = admin.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "zip"},
        )
        conflict = admin.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers=headers,
            json={"kind": "json"},
        )
        assert created.status_code == repeated.status_code == 202
        assert created.json()["id"] == repeated.json()["id"]
        assert conflict.status_code == 409
        assert queued == [UUID(created.json()["id"])]

        with Session(engine, expire_on_commit=False) as session:
            process_export_task(
                session,
                UUID(created.json()["id"]),
                storage,
            )
        completed = admin.get(
            f"/v1/workspaces/{workspace_id}/exports/{created.json()['id']}"
        )
        assert completed.status_code == 200
        assert completed.json()["status"] == "succeeded"
        assert completed.json()["mime_type"] == "application/zip"
        assert completed.json()["file_name"].endswith(".zip")
        assert completed.json()["download_url"].startswith(
            "https://storage.test/"
        )

        editor = _login_role(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            role="editor",
        )
        editor_response = editor.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={"Idempotency-Key": "editor-full-backup"},
            json={"kind": "zip"},
        )
        viewer = _login_role(
            admin,
            workspace_id=workspace_id,
            csrf=csrf,
            role="viewer",
        )
        denied = viewer.post(
            f"/v1/workspaces/{workspace_id}/exports",
            headers={"Idempotency-Key": "viewer-full-backup"},
            json={"kind": "zip"},
        )
        assert editor_response.status_code == 202
        assert denied.status_code == 403
        editor.close()
        viewer.close()


def test_zip_export_missing_source_fails_without_publishing_half_archive() -> None:
    storage = MemoryFullBackupStorage()
    with configured_client() as (client, engine):
        workspace_id, _, _, _ = _seed_portable_workspace(client, engine)
        context = _context(client, engine, workspace_id)
        from app.modules.exports.models import ExportKind
        from app.modules.exports.service import create_export_task

        with Session(engine, expire_on_commit=False) as session:
            task, _ = create_export_task(
                session,
                context,
                kind=ExportKind.ZIP,
                content_id=None,
                idempotency_key="missing-source",
            )
            session.commit()
            task_id = task.id
            process_export_task(session, task_id, storage)
        with Session(engine) as session:
            failed = session.get(ExportTask, task_id)
            assert failed is not None
            assert failed.status is ExportStatus.FAILED
            assert failed.object_key is None
            assert failed.file_name is None
        assert not any(
            key.startswith(f"workspaces/{workspace_id}/exports/")
            for key in storage.objects
        )

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.main import create_app
from app.core.rate_limit import InMemoryAtomicBackend, default_rate_limiter
from app.modules.exports.router import ExportCreate, create_export


REPO_ROOT = Path(__file__).resolve().parents[4]


def test_lite_settings_select_local_single_process_backends() -> None:
    settings = Settings(
        _env_file=None,
        app_lite_mode=True,
        storage_backend="local",
    )

    assert settings.app_lite_mode is True
    assert settings.storage_backend == "local"
    assert settings.run_tasks_inline is True


def test_lite_rate_limiter_does_not_require_redis(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        app_mock_mode=False,
        app_lite_mode=True,
        storage_backend="local",
        database_url="postgresql+psycopg://user:strong-password@postgres/app",
        session_signing_secret="s" * 32,
        model_secret_encryption_key="m" * 32,
        storage_signing_secret="t" * 32,
    )
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)

    limiter = default_rate_limiter()

    assert isinstance(limiter._backend, InMemoryAtomicBackend)


def test_lite_compose_has_only_three_long_running_services() -> None:
    compose_file = REPO_ROOT / "infra/docker/compose.lite.yml"
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "--services"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    services = set(result.stdout.splitlines())
    assert {"postgres", "migrate", "storage-init", "api", "web"} == services
    assert {"redis", "object-storage", "bucket-init", "worker"}.isdisjoint(services)


def test_lite_compose_sets_resource_limits_and_local_storage() -> None:
    compose_file = REPO_ROOT / "infra/docker/compose.lite.yml"
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rendered = result.stdout
    assert "APP_LITE_MODE: \"true\"" in rendered
    assert "STORAGE_BACKEND: local" in rendered
    assert "LOCAL_STORAGE_PATH: /data/objects" in rendered
    assert "memory: \"671088640\"" in rendered  # API: 640 MiB
    assert "memory: \"402653184\"" in rendered  # PostgreSQL: 384 MiB
    assert "memory: \"268435456\"" in rendered  # Web: 256 MiB


def test_lite_api_hides_advanced_governance_and_recovery_routes() -> None:
    application = create_app(
        Settings(_env_file=None, app_lite_mode=True, storage_backend="local")
    )
    paths = set(application.openapi()["paths"])

    assert "/v1/workspaces/{workspace_id}/contents" in paths
    assert "/v1/workspaces/{workspace_id}/agent/chats" in paths
    assert "/v1/workspaces/{workspace_id}/exports" in paths
    assert "/v1/workspaces/{workspace_id}/risk-scans" in paths
    assert not any("zip-restores" in path for path in paths)
    assert not any("restore-previews" in path for path in paths)
    assert not any("risk-documents" in path for path in paths)
    assert not any("risk-feedback" in path for path in paths)
    assert not any("analytics" in path for path in paths)


def test_full_api_keeps_advanced_routes_available() -> None:
    application = create_app(
        Settings(_env_file=None, app_lite_mode=False, storage_backend="s3")
    )
    paths = set(application.openapi()["paths"])

    assert any("zip-restores" in path for path in paths)
    assert any("restore-previews" in path for path in paths)
    assert any("risk-documents" in path for path in paths)


def test_lite_api_rejects_full_zip_export(monkeypatch) -> None:
    settings = Settings(_env_file=None, app_lite_mode=True, storage_backend="local")
    monkeypatch.setattr("app.modules.exports.router.get_settings", lambda: settings)

    with pytest.raises(HTTPException) as error:
        create_export(
            workspace_id=uuid4(),
            data=ExportCreate(kind="zip", content_id=None),
            session=None,  # type: ignore[arg-type]
            enqueuer=lambda _task_id: None,
            idempotency_key="lite-zip-export",
        )

    assert error.value.status_code == 422
    assert error.value.detail == "ZIP full backup is unavailable in Lite mode"

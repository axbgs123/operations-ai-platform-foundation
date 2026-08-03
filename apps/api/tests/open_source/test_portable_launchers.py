from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[4]
PORTABLE = ROOT / "portable"
MAC_START = PORTABLE / "启动运营工具-macOS.command"
MAC_STOP = PORTABLE / "停止运营工具-macOS.command"
WINDOWS_START = PORTABLE / "启动运营工具-Windows.bat"
WINDOWS_STOP = PORTABLE / "停止运营工具-Windows.bat"
GUIDE = PORTABLE / "使用说明.txt"

pytestmark = pytest.mark.security


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_portable_local_state_is_ignored_and_release_allowlisted() -> None:
    """Removing either boundary could publish machine-local credentials."""
    assert ".local-state/" in _text(ROOT / ".gitignore").splitlines()
    security = _text(ROOT / "scripts/release-security.py")
    assert 'r"portable/' in security
    assert r"\.(?:bat|command|txt)" in security


def test_stop_launchers_preserve_volumes_and_use_the_portable_project() -> None:
    """A destructive or mismatched stop command could lose or strand local data."""
    for path in (MAC_STOP, WINDOWS_STOP):
        text = _text(path)
        assert " down" in text
        assert "--volumes" not in text
        assert "volume rm" not in text.lower()
        assert "operations-ai-local" in text
        assert "PORTABLE_COMPOSE_PROJECT" in text


def test_start_launchers_preserve_existing_environment_and_bootstrap() -> None:
    """A repeat start must not overwrite configuration or recreate a workspace."""
    mac = _text(MAC_START)
    windows = _text(WINDOWS_START)
    assert "cp -n .env.example .env" in mac
    assert "if not exist .env copy /Y .env.example .env" in windows
    for text in (mac, windows):
        assert ".local-state" in text
        assert "bootstrap.json" in text
        assert "/v1/workspaces" in text
        assert "PORTABLE_NO_OPEN" in text


def test_mac_launchers_are_strict_and_resolve_their_own_location() -> None:
    """Launching from Finder must not depend on the caller's working directory."""
    for path in (MAC_START, MAC_STOP):
        text = _text(path)
        assert text.startswith("#!/usr/bin/env bash\n")
        assert "set -Eeuo pipefail" in text
        assert "BASH_SOURCE[0]" in text
        assert path.stat().st_mode & 0o111


def test_windows_launchers_check_supported_docker_without_extra_runtimes() -> None:
    """Windows startup must fail safely when Docker Compose v2 is unavailable."""
    for path in (WINDOWS_START, WINDOWS_STOP):
        text = _text(path)
        assert text.startswith("@echo off")
        assert "setlocal" in text.lower()
        assert "%~dp0.." in text
    start = _text(WINDOWS_START).lower()
    assert "where docker" in start
    assert "docker info" in start
    assert "docker compose version" in start
    assert all(tool not in start for tool in ("python ", "node ", "jq ", "wsl "))


def test_start_launchers_expose_only_bounded_portable_overrides() -> None:
    """Hard-coded ports or project names would make isolated installs collide."""
    mac = _text(MAC_START)
    windows = _text(WINDOWS_START)
    for name in (
        "PORTABLE_COMPOSE_PROJECT",
        "API_PORT",
        "WEB_PORT",
        "PORTABLE_NO_OPEN",
    ):
        assert name in mac
        assert name in windows
    assert "${PORTABLE_COMPOSE_PROJECT:-operations-ai-local}" in mac
    assert "${API_PORT:-8000}" in mac
    assert "${WEB_PORT:-3000}" in mac
    assert "operations-ai-local" in windows


def test_start_launchers_wait_boundedly_and_fail_when_services_never_ready() -> None:
    """A launcher must not report success or wait forever when a service is down."""
    mac = _text(MAC_START)
    windows = _text(WINDOWS_START)
    assert "/health/ready" in mac
    assert "/enter" in mac
    assert "120" in mac
    assert "60" in mac
    assert "exit 1" in mac
    assert "/health/ready" in windows
    assert "/enter" in windows
    assert "Invoke-WebRequest" in windows
    assert "120" in windows
    assert "60" in windows
    assert "exit /b 1" in windows.lower()


def test_bootstrap_is_validated_and_atomically_published_without_log_echo() -> None:
    """A partial response must never become initialized state or leak an invite code."""
    mac = _text(MAC_START)
    windows = _text(WINDOWS_START)
    assert "bootstrap.json.tmp" in mac
    assert "plutil -extract workspace_id" in mac
    assert "plutil -extract admin_code" in mac
    assert 'mv "$bootstrap_tmp" "$bootstrap_file"' in mac
    assert 'echo "$admin_code"' not in mac
    assert "bootstrap.json.tmp" in windows
    assert ".workspace_id" in windows
    assert ".admin_code" in windows
    assert "Move-Item" in windows
    assert "ECHO %ADMIN_CODE%" not in windows.upper()


def test_launchers_open_private_entry_and_support_headless_acceptance() -> None:
    """A writable install must enter through /enter and remain testable headlessly."""
    mac = _text(MAC_START)
    windows = _text(WINDOWS_START)
    assert 'open "http://127.0.0.1:${web_port}/enter"' in mac
    assert 'start "" "http://127.0.0.1:%WEB_PORT%/enter"' in windows
    assert 'open "http://127.0.0.1:${web_port}/demo"' not in mac
    assert 'start "" "http://127.0.0.1:%WEB_PORT%/demo"' not in windows
    assert 'PORTABLE_NO_OPEN:-0' in mac
    assert "PORTABLE_NO_OPEN" in windows


def test_usage_guide_states_prerequisites_security_and_validation_limits() -> None:
    """Removing an operational warning could make an unsafe install look supported."""
    guide = _text(GUIDE)
    for required in (
        "Docker Desktop",
        "8 GB",
        "10 GB",
        "5–15 分钟",
        "3000",
        "8000",
        "55432",
        "9000",
        "9001",
        "Mock",
        "Windows",
        "not_run",
        ".local-state/首次登录信息.txt",
        "ZIP",
    ):
        assert required in guide
    assert "首次启动" in guide
    assert "网络" in guide
    assert "正常停止" in guide
    assert "不会删除" in guide
    assert "千问" in guide

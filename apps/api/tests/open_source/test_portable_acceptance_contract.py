from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "scripts" / "verify-portable-release.sh"
MAC_START = ROOT / "portable" / "启动运营工具-macOS.command"
MAC_STOP = ROOT / "portable" / "停止运营工具-macOS.command"
GUIDE = ROOT / "portable" / "使用说明.txt"

pytestmark = pytest.mark.security


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_acceptance_runner_requires_an_explicit_artifact_or_build_mode() -> None:
    """Silently choosing an old ZIP could validate the wrong source commit."""
    result = subprocess.run(
        ["bash", str(RUNNER)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "必须明确指定 --zip 或 --build" in result.stderr


def test_acceptance_runner_uses_only_an_unpacked_isolated_mac_install() -> None:
    """Using repository launchers or fixed ports could touch a developer install."""
    script = _text(RUNNER)

    assert 'project_prefix="operations_ai_portable_test_"' in script
    assert "mktemp -d" in script
    assert "select_loopback_port" in script
    assert 'PORTABLE_NO_OPEN="1"' in script
    assert 'unpacked_root/启动运营工具-macOS.command' in script
    assert 'portable/启动运营工具-macOS.command' not in script
    for variable in (
        "API_PORT",
        "WEB_PORT",
        "POSTGRES_PORT",
        "S3_PORT",
        "S3_CONSOLE_PORT",
        "NEXT_PUBLIC_API_URL",
        "WEB_ORIGIN",
    ):
        assert variable in script
    assert "/health/ready" in script
    assert "/enter" in script


def test_acceptance_runner_records_only_the_packaged_extension_version() -> None:
    """Portable evidence may identify the extension build, never its pairing secret."""
    script = _text(RUNNER)

    assert 'expected_extension_version="0.3.0"' in script
    assert 'extension_version' in script
    assert 'apps/extension/manifest.json' in script


def test_acceptance_runner_uses_atomic_owner_and_independent_editor_flows() -> None:
    """Reintroducing bootstrap or reusing the owner session would bypass onboarding."""
    script = _text(RUNNER)

    assert "/v1/workspaces/onboard" in script
    assert "/members/codes" in script
    assert '"role":"editor"' in script
    assert "/v1/sessions/invite" in script
    assert "admin_cookie_jar" in script
    assert "editor_cookie_jar" in script
    assert "admin_csrf_file" in script
    assert "chmod 600" in script
    assert ".local-state/bootstrap.json" in script
    assert ".local-state/首次登录信息.txt" in script
    assert "assert_file_absent" in script


def test_acceptance_runner_creates_and_rechecks_fixture_without_resetting_volumes() -> None:
    """A smoke-only run would miss data loss and duplicate initialization."""
    script = _text(RUNNER)

    assert "/accounts" in script
    assert "/v1/contents" in script
    assert "stop_launcher" in script
    assert "member_count_before_restart" in script
    assert "member_count_after_restart" in script
    assert "member_count_after_second_start" in script
    assert "verify_persisted_fixture" in script
    assert "run_unpacked_launcher" in script
    assert script.count("run_unpacked_launcher") >= 3
    assert "--volumes" not in _text(ROOT / "portable" / "停止运营工具-macOS.command")


def test_acceptance_evidence_schema_excludes_credentials_and_user_copy() -> None:
    """Evidence must remain shareable without exposing login or content material."""
    script = _text(RUNNER)

    assert "portable-acceptance.json" in script
    assert "macos_runtime" in script
    assert "source_commit" in script
    assert "zip_sha256" in script
    assert "docker_version" in script
    assert "docker_compose_version" in script
    assert "workspace_id" in script
    assert "owner_member_id" in script
    assert "editor_member_id" in script
    assert "account_id" in script
    assert "content_id" in script
    assert (
        'evidence_allowed_fields="schema_version macos_runtime source_commit '
        'zip_sha256 extension_version started_at finished_at docker_version '
        'docker_compose_version workspace_id owner_member_id editor_member_id '
        'account_id content_id member_count shortcut_assignment device_renewal '
        'full_page_completeness redaction_default cleanup not_run"'
    ) in script
    evidence_block = script.split("# EVIDENCE_START", 1)[1].split(
        "# EVIDENCE_END", 1
    )[0]
    for field in (
        '"shortcut_assignment"',
        '"device_renewal"',
        '"full_page_completeness"',
        '"redaction_default"',
        '"not_run"',
    ):
        assert field in evidence_block
    for not_run_item in (
        '"mock_upload"',
        '"web_manual_confirmation"',
        '"staging_object_cleanup"',
    ):
        assert not_run_item in evidence_block
    for forbidden_key in (
        '"invite_code"',
        '"cookie"',
        '"csrf_token"',
        '"display_name"',
        '"workspace_name"',
        '"prompt"',
    ):
        assert forbidden_key not in evidence_block


def test_acceptance_cleanup_is_prefix_guarded_and_removes_only_test_resources() -> None:
    """A broad cleanup command could delete unrelated Docker data."""
    script = _text(RUNNER)

    assert '[[ "$project_name" == "$project_prefix"* ]]' in script
    assert "refusing to clean non-test project" in script
    assert "trap cleanup EXIT" in script
    assert "--volumes --remove-orphans" in script
    assert "verify_project_absent" in script
    assert 'rm -rf "$temporary_root"' in script
    assert "docker system prune" not in script
    assert "docker volume prune" not in script


def test_mac_launcher_passes_only_explicit_acceptance_overrides() -> None:
    """Persisting test ports or accepting arbitrary names would pollute local state."""
    launcher = _text(MAC_START)

    for variable in (
        "PORTABLE_COMPOSE_PROJECT",
        "API_PORT",
        "WEB_PORT",
        "POSTGRES_PORT",
        "S3_PORT",
        "S3_CONSOLE_PORT",
        "NEXT_PUBLIC_API_URL",
        "WEB_ORIGIN",
        "PORTABLE_NO_OPEN",
    ):
        assert variable in launcher
    assert 'root_dir="$script_dir"' in launcher
    assert 'root_dir="$script_dir"' in _text(MAC_STOP)
    assert "bootstrap.json" not in launcher
    assert "首次登录信息.txt" not in launcher
    assert "env >>" not in launcher


def _fake_mac_install(tmp_path: Path) -> tuple[Path, Path, Path]:
    install = tmp_path / "中文安装目录" / "portable"
    install.mkdir(parents=True)
    shutil.copy2(MAC_START, install / MAC_START.name)
    (install / "infra/docker").mkdir(parents=True)
    (install / "infra/docker/compose.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    (install / ".env.example").write_text(
        "APP_MOCK_MODE=true\n",
        encoding="utf-8",
    )
    (install / ".env").write_text(
        "PRESERVE=existing\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    call_log = tmp_path / "docker-calls.log"
    _executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$DOCKER_CALL_LOG"
if [[ -n "${FAIL_BUILD_SERVICE:-}" ]] \
  && [[ "$*" == *" build ${FAIL_BUILD_SERVICE}" ]]; then
  exit 31
fi
exit 0
""",
    )
    _executable(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")
    return install, bin_dir, call_log


def test_mac_launcher_builds_images_sequentially_before_starting(
    tmp_path: Path,
) -> None:
    """Compose v5 Bake must never receive a multi-target build in a Unicode path."""
    install, bin_dir, call_log = _fake_mac_install(tmp_path)

    result = subprocess.run(
        ["bash", str(install / MAC_START.name)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DOCKER_CALL_LOG": str(call_log),
            "PORTABLE_NO_OPEN": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (install / ".env").read_text(encoding="utf-8") == (
        "PRESERVE=existing\n"
    )
    assert "运营工具已就绪" in result.stdout
    compose_calls = [
        line
        for line in call_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("compose --project-name")
    ]
    assert compose_calls[-3:] == [
        (
            "compose --project-name operations-ai-local --env-file "
            f"{install}/.env -f {install}/infra/docker/compose.yml build api"
        ),
        (
            "compose --project-name operations-ai-local --env-file "
            f"{install}/.env -f {install}/infra/docker/compose.yml build web"
        ),
        (
            "compose --project-name operations-ai-local --env-file "
            f"{install}/.env -f {install}/infra/docker/compose.yml "
            "--profile demo up -d --no-build"
        ),
    ]
    assert not any(" up " in call and "--build" in call for call in compose_calls)
    assert not any("build api web" in call for call in compose_calls)


@pytest.mark.parametrize(
    ("failed_service", "expected_error"),
    [
        ("api", "API 镜像构建失败。未启动任何服务"),
        ("web", "Web 镜像构建失败。未启动任何服务"),
    ],
)
def test_mac_launcher_does_not_start_services_after_an_image_build_failure(
    tmp_path: Path,
    failed_service: str,
    expected_error: str,
) -> None:
    install, bin_dir, call_log = _fake_mac_install(tmp_path)

    result = subprocess.run(
        ["bash", str(install / MAC_START.name)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "DOCKER_CALL_LOG": str(call_log),
            "FAIL_BUILD_SERVICE": failed_service,
            "PORTABLE_NO_OPEN": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    compose_calls = call_log.read_text(encoding="utf-8").splitlines()
    assert not any(" up " in call for call in compose_calls)
    if failed_service == "api":
        assert not any("build web" in call for call in compose_calls)


def test_mac_acceptance_documentation_is_honest_about_current_scope() -> None:
    """Local macOS acceptance must not be presented as Windows or release readiness."""
    guide = _text(GUIDE)

    assert "macOS 本地解压包验收" in guide
    assert "Windows" in guide
    assert "not_run" in guide
    assert "GitHub Release" in guide
    assert "暂未执行" in guide
    assert "真实平台" in guide
    assert "真实模型" in guide

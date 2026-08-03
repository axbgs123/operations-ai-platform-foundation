from __future__ import annotations

from datetime import datetime, timezone
from functools import cache
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType
import warnings
import zipfile

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
BUILDER_PATH = REPO_ROOT / "scripts" / "build-portable-release.py"
SECURITY_TOOL = REPO_ROOT / "scripts" / "release-security.py"
SOURCE_EPOCH = 1_785_744_000
VERSION = "0.1.0"
ROOT_LAUNCHERS = {
    "启动运营工具-macOS.command",
    "停止运营工具-macOS.command",
    "启动运营工具-Windows.bat",
    "停止运营工具-Windows.bat",
}

pytestmark = pytest.mark.security


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def _must_run(*args: str, cwd: Path) -> None:
    result = _run(*args, cwd=cwd)
    assert result.returncode == 0, result.stderr


def _commit(repo: Path, message: str) -> None:
    _must_run("git", "add", "--all", cwd=repo)
    _must_run("git", "commit", "-qm", message, cwd=repo)


def _write(repo: Path, relative: str, content: str | bytes) -> Path:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _new_release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _must_run("git", "init", "-q", cwd=repo)
    _must_run("git", "config", "user.email", "portable@example.invalid", cwd=repo)
    _must_run("git", "config", "user.name", "Portable Fixture", cwd=repo)
    _write(repo, ".env.example", "APP_MOCK_MODE=true\n")
    _write(repo, "README.md", "合成便携发布测试\n")
    _write(repo, "infra/docker/compose.yml", "services: {}\n")
    _write(repo, "apps/api/app/main.py", "APP = 'synthetic'\n")
    _write(repo, "apps/web/src/app/page.tsx", "export default function Page() { return null; }\n")
    _write(repo, "portable/使用说明.txt", "合成使用说明\n")
    for name in sorted(ROOT_LAUNCHERS):
        path = _write(repo, f"portable/{name}", "@echo off\n" if name.endswith(".bat") else "#!/usr/bin/env bash\n")
        if name.endswith(".command"):
            path.chmod(0o755)
    _commit(repo, "synthetic portable source")
    return repo


@cache
def _builder() -> ModuleType:
    assert BUILDER_PATH.is_file(), "portable release builder is missing"
    spec = importlib.util.spec_from_file_location("portable_release_builder", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts_path = str(BUILDER_PATH.parent)
    sys.path.insert(0, scripts_path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts_path)
    return module


def _build(repo: Path, output: Path, *, version: str = VERSION, epoch: int = SOURCE_EPOCH):
    return _builder().build_portable_release(
        repository=repo,
        output_dir=output,
        version=version,
        source_date_epoch=epoch,
    )


def _verify(path: Path) -> subprocess.CompletedProcess[str]:
    return _run(
        sys.executable,
        str(SECURITY_TOOL),
        "verify-portable-release",
        "--path",
        str(path),
        cwd=REPO_ROOT,
    )


def _refresh_checksum(path: Path) -> None:
    digest = sha256(path.read_bytes()).hexdigest()
    (path.parent / "checksums.txt").write_text(
        f"{digest}  {path.name}\n",
        encoding="utf-8",
    )


def _write_zip(path: Path, entries: list[tuple[str, bytes, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload, mode in entries:
                info = zipfile.ZipInfo(name, (2026, 8, 3, 8, 0, 0))
                info.create_system = 3
                info.external_attr = mode << 16
                archive.writestr(info, payload)
    _refresh_checksum(path)


def _mark_first_entry_encrypted(path: Path) -> None:
    payload = bytearray(path.read_bytes())
    for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = payload.find(signature)
        assert position >= 0
        current = int.from_bytes(
            payload[position + flag_offset : position + flag_offset + 2],
            "little",
        )
        payload[position + flag_offset : position + flag_offset + 2] = (
            current | 1
        ).to_bytes(2, "little")
    path.write_bytes(payload)
    _refresh_checksum(path)


def _rewrite_valid_zip(
    path: Path,
    *,
    content_override: dict[str, bytes] | None = None,
    mode_override: dict[str, int] | None = None,
    extra: tuple[str, bytes, int] | None = None,
) -> None:
    content_override = content_override or {}
    mode_override = mode_override or {}
    replacement = path.with_suffix(".replacement.zip")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(
        replacement,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as target:
        for original in source.infolist():
            info = zipfile.ZipInfo(original.filename, original.date_time)
            info.create_system = original.create_system
            info.external_attr = mode_override.get(
                original.filename,
                (original.external_attr >> 16) & 0xFFFF,
            ) << 16
            target.writestr(
                info,
                content_override.get(original.filename, source.read(original)),
            )
        if extra is not None:
            name, payload, mode = extra
            info = zipfile.ZipInfo(name, (2026, 8, 3, 8, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            target.writestr(info, payload)
    replacement.replace(path)
    _refresh_checksum(path)


def test_builder_rejects_non_numeric_semantic_versions(tmp_path: Path) -> None:
    """Accepting aliases such as latest would make release identity ambiguous."""
    repo = _new_release_repo(tmp_path)

    with pytest.raises(ValueError, match="semantic version"):
        _build(repo, tmp_path / "out", version="latest")


def test_builder_rejects_epochs_before_the_zip_format_minimum(tmp_path: Path) -> None:
    """Clamping old timestamps would hide a non-reproducible build input."""
    repo = _new_release_repo(tmp_path)

    with pytest.raises(ValueError, match="1980"):
        _build(repo, tmp_path / "out", epoch=0)


def test_builder_ignores_untracked_files_but_rejects_tracked_changes(tmp_path: Path) -> None:
    """Reading the working directory could package protected or half-edited files."""
    repo = _new_release_repo(tmp_path)
    _write(repo, ".superpowers/brainstorm/private.md", "must remain untracked\n")
    _write(repo, "untracked.txt", "must not ship\n")

    result = _build(repo, tmp_path / "clean-output")
    with zipfile.ZipFile(result.zip_path) as archive:
        names = archive.namelist()
    assert ".superpowers/brainstorm/private.md" not in names
    assert "untracked.txt" not in names

    _write(repo, "README.md", "dirty tracked content\n")
    with pytest.raises(ValueError, match="tracked worktree"):
        _build(repo, tmp_path / "dirty-output")


def test_builder_rejects_tracked_symlinks(tmp_path: Path) -> None:
    """Following a tracked symlink could copy data from outside the source tree."""
    repo = _new_release_repo(tmp_path)
    link = repo / "docs/open-source/synthetic.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(repo / "README.md")
    _commit(repo, "add unsafe symlink")

    with pytest.raises(ValueError, match="symlink"):
        _build(repo, tmp_path / "out")


@pytest.mark.parametrize(
    "relative",
    (
        ".env",
        ".local-state/bootstrap.json",
        "workspace.db",
        "workspace-dump.sql",
        "workspace-backup.zip",
        "server-private.key",
        "server-certificate.pem",
        "apps/web/src/app/unreviewed.bin",
    ),
)
def test_builder_rejects_sensitive_or_non_allowlisted_tracked_paths(
    tmp_path: Path,
    relative: str,
) -> None:
    """A tracked file is not automatically safe enough for a public package."""
    repo = _new_release_repo(tmp_path)
    _write(repo, relative, b"synthetic forbidden release input")
    _commit(repo, f"add {relative}")

    with pytest.raises(ValueError, match="forbidden|allowlist"):
        _build(repo, tmp_path / "out")


def test_builder_rejects_oversized_allowlisted_source_files(tmp_path: Path) -> None:
    """An allowlisted extension must not bypass the per-file resource limit."""
    repo = _new_release_repo(tmp_path)
    large = repo / "docs/open-source/large.md"
    large.parent.mkdir(parents=True)
    with large.open("wb") as stream:
        stream.seek(20 * 1024 * 1024)
        stream.write(b"x")
    _commit(repo, "add oversized source")

    with pytest.raises(ValueError, match="size limit"):
        _build(repo, tmp_path / "out")


def test_builder_accepts_only_reviewed_visual_regression_baselines(
    tmp_path: Path,
) -> None:
    """A governed baseline may ship, but a newly tracked PNG needs explicit review."""
    repo = _new_release_repo(tmp_path)
    reviewed = (
        "tests/e2e/workbench-visual.spec.ts-snapshots/overview-darwin.png"
    )
    _write(repo, reviewed, b"\x89PNG\r\n\x1a\nsynthetic reviewed baseline")
    _commit(repo, "add reviewed visual baseline")

    result = _build(repo, tmp_path / "reviewed-output")
    with zipfile.ZipFile(result.zip_path) as archive:
        assert archive.read(reviewed).endswith(b"synthetic reviewed baseline")

    unreviewed = (
        "tests/e2e/workbench-visual.spec.ts-snapshots/"
        "future-unreviewed-darwin.png"
    )
    _write(repo, unreviewed, b"\x89PNG\r\n\x1a\nsynthetic unreviewed baseline")
    _commit(repo, "add unreviewed visual baseline")
    with pytest.raises(ValueError, match="allowlist"):
        _build(repo, tmp_path / "unreviewed-output")


def test_builder_emits_sorted_normalized_manifested_payload(tmp_path: Path) -> None:
    """Wrong mapping, mode, newline, timestamp, or manifest data breaks portability."""
    repo = _new_release_repo(tmp_path)

    result = _build(repo, tmp_path / "out")

    with zipfile.ZipFile(result.zip_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        assert names == sorted(names, key=lambda value: value.encode("utf-8"))
        assert ROOT_LAUNCHERS < set(names)
        assert not any(name.startswith("portable/") for name in names)
        expected_time = datetime.fromtimestamp(
            SOURCE_EPOCH,
            tz=timezone.utc,
        ).timetuple()[:6]
        assert all(info.date_time == expected_time for info in infos)
        for name in ROOT_LAUNCHERS:
            info = archive.getinfo(name)
            expected_mode = 0o755 if name.endswith(".command") else 0o644
            assert ((info.external_attr >> 16) & 0o777) == expected_mode
        for name in (item for item in ROOT_LAUNCHERS if item.endswith(".bat")):
            payload = archive.read(name)
            assert b"\r\n" in payload
            assert b"\n" not in payload.replace(b"\r\n", b"")
        assert archive.read("README.md").decode("utf-8") == "合成便携发布测试\n"
        internal_manifest = archive.read("release-manifest.json")

    external_manifest = (result.zip_path.parent / "release-manifest.json").read_bytes()
    assert internal_manifest == external_manifest
    manifest = json.loads(internal_manifest)
    assert manifest["version"] == VERSION
    assert manifest["source_commit"] == _run(
        "git",
        "rev-parse",
        "HEAD",
        cwd=repo,
    ).stdout.strip()
    assert manifest["source_date_epoch"] == SOURCE_EPOCH
    declared = {entry["path"]: entry for entry in manifest["files"]}
    assert set(declared) == set(names)
    assert declared["release-manifest.json"]["sha256"] is None
    assert declared["release-manifest.json"]["size"] == len(internal_manifest)
    with zipfile.ZipFile(result.zip_path) as archive:
        for name, entry in declared.items():
            if name == "release-manifest.json":
                continue
            payload = archive.read(name)
            assert entry["size"] == len(payload)
            assert entry["sha256"] == sha256(payload).hexdigest()
    assert result.file_count == len(names)


def test_builder_is_reproducible_and_changes_with_committed_content(
    tmp_path: Path,
) -> None:
    """A build must depend on committed content, not filesystem iteration or temp names."""
    repo = _new_release_repo(tmp_path)

    first = _build(repo, tmp_path / "out-a")
    second = _build(repo, tmp_path / "out-b")
    assert first.sha256 == second.sha256
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()

    _write(repo, "README.md", "changed committed payload\n")
    _commit(repo, "change payload")
    changed = _build(repo, tmp_path / "out-c")
    assert changed.sha256 != first.sha256


def test_builder_writes_external_checksum_without_recursive_zip_hash(
    tmp_path: Path,
) -> None:
    """Putting the ZIP hash inside itself would make deterministic hashing impossible."""
    repo = _new_release_repo(tmp_path)

    result = _build(repo, tmp_path / "out")

    checksum = (result.zip_path.parent / "checksums.txt").read_text(encoding="utf-8")
    assert checksum == f"{result.sha256}  {result.zip_path.name}\n"
    with zipfile.ZipFile(result.zip_path) as archive:
        assert "checksums.txt" not in archive.namelist()
        manifest = json.loads(archive.read("release-manifest.json"))
    assert all(entry["sha256"] != result.sha256 for entry in manifest["files"])


def test_portable_verifier_accepts_a_builder_artifact(tmp_path: Path) -> None:
    """The independent verifier and builder must agree on the governed contract."""
    repo = _new_release_repo(tmp_path)
    result = _build(repo, tmp_path / "out")

    verified = _verify(result.zip_path)

    assert verified.returncode == 0, verified.stderr
    assert verified.stdout.strip() == "portable_release=clean"


@pytest.mark.parametrize(
    "names",
    (
        ("README.md", "README.md"),
        ("README.md", "readme.md"),
        ("docs/é.md", "docs/e\u0301.md"),
    ),
)
def test_portable_verifier_rejects_duplicate_or_colliding_paths(
    tmp_path: Path,
    names: tuple[str, str],
) -> None:
    """Case or Unicode aliases can overwrite a different file on extraction."""
    archive = tmp_path / "collision.zip"
    _write_zip(
        archive,
        [(names[0], b"first", 0o644), (names[1], b"second", 0o644)],
    )

    verified = _verify(archive)

    assert verified.returncode == 1
    assert "colliding path" in verified.stderr


@pytest.mark.parametrize(
    ("name", "mode", "encrypted", "diagnostic"),
    (
        ("../escape.txt", 0o644, False, "unsafe archive path"),
        ("/absolute.txt", 0o644, False, "unsafe archive path"),
        ("C:/drive.txt", 0o644, False, "unsafe archive path"),
        ("linked.txt", stat.S_IFLNK | 0o777, False, "symlink"),
        ("encrypted.txt", 0o644, True, "encrypted"),
        (".env", 0o644, False, "forbidden"),
    ),
)
def test_portable_verifier_rejects_unsafe_archive_members(
    tmp_path: Path,
    name: str,
    mode: int,
    encrypted: bool,
    diagnostic: str,
) -> None:
    """An archive must be safe before any extractor sees its members."""
    archive = tmp_path / "unsafe.zip"
    _write_zip(archive, [(name, b"synthetic", mode)])
    if encrypted:
        _mark_first_entry_encrypted(archive)

    verified = _verify(archive)

    assert verified.returncode == 1
    assert diagnostic in verified.stderr


@pytest.mark.parametrize(
    ("mutation", "diagnostic"),
    (
        ("content", "hash mismatch"),
        ("uncovered", "manifest does not cover"),
        ("executable", "unexpected executable"),
    ),
)
def test_portable_verifier_rejects_payload_manifest_divergence(
    tmp_path: Path,
    mutation: str,
    diagnostic: str,
) -> None:
    """Checksum validity alone must not authorize altered archive contents."""
    repo = _new_release_repo(tmp_path)
    result = _build(repo, tmp_path / "out")
    if mutation == "content":
        _rewrite_valid_zip(
            result.zip_path,
            content_override={"README.md": b"tampered\n"},
        )
    elif mutation == "uncovered":
        _rewrite_valid_zip(
            result.zip_path,
            extra=("docs/open-source/extra.md", b"extra\n", 0o644),
        )
    else:
        _rewrite_valid_zip(
            result.zip_path,
            mode_override={"README.md": 0o755},
        )

    verified = _verify(result.zip_path)

    assert verified.returncode == 1
    assert diagnostic in verified.stderr


def test_portable_verifier_rejects_missing_runtime_contract_files(
    tmp_path: Path,
) -> None:
    """A syntactically valid ZIP without the full runtime must not pass release."""
    archive = tmp_path / "incomplete.zip"
    _write_zip(
        archive,
        [
            (
                "release-manifest.json",
                b'{"version":"0.1.0","files":[]}\n',
                0o644,
            )
        ],
    )

    verified = _verify(archive)

    assert verified.returncode == 1
    assert "missing required portable entry" in verified.stderr

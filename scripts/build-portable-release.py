#!/usr/bin/env python3
"""Build a deterministic portable ZIP from a clean tracked Git tree."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile

from release_policy import (
    MAX_SOURCE_FILE_BYTES,
    release_path_forbidden_reason,
    source_path_is_allowlisted,
    source_path_is_binary,
)


SEMANTIC_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
ZIP_MINIMUM_EPOCH = int(datetime(1980, 1, 1, tzinfo=timezone.utc).timestamp())
PORTABLE_ROOT_MAPPING = {
    "portable/启动运营工具-macOS.command": "启动运营工具-macOS.command",
    "portable/停止运营工具-macOS.command": "停止运营工具-macOS.command",
    "portable/启动运营工具-Windows.bat": "启动运营工具-Windows.bat",
    "portable/停止运营工具-Windows.bat": "停止运营工具-Windows.bat",
    "portable/使用说明.txt": "使用说明.txt",
}


@dataclass(frozen=True)
class PortableBuildResult:
    zip_path: Path
    sha256: str
    file_count: int


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int
    mode: int
    sha256: str | None


@dataclass(frozen=True)
class _Payload:
    path: str
    content: bytes
    mode: int


def _git(repository: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        text=False,
        capture_output=True,
    )
    return result.stdout


def tracked_paths(repository: Path) -> tuple[str, ...]:
    raw = _git(repository, "ls-files", "--cached", "-z")
    paths = (item.decode("utf-8") for item in raw.split(b"\0") if item)
    return tuple(sorted(paths, key=lambda value: value.encode("utf-8")))


def _tracked_modes(repository: Path) -> dict[str, int]:
    raw = _git(repository, "ls-files", "--stage", "-z")
    modes: dict[str, int] = {}
    for record in (item for item in raw.split(b"\0") if item):
        metadata, encoded_path = record.split(b"\t", 1)
        mode_text, _, stage_text = metadata.split()
        if stage_text != b"0":
            raise ValueError("release source contains an unmerged Git index entry")
        mode = int(mode_text, 8)
        modes[encoded_path.decode("utf-8")] = mode
    return modes


def validate_release_path(path: str) -> None:
    if (
        not path
        or "\0" in path
        or "\\" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
    ):
        raise ValueError(f"unsafe release path: {path!r}")
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe release path: {path!r}")
    reason = release_path_forbidden_reason(path)
    if reason is not None:
        raise ValueError(f"{reason}: {path}")
    if not source_path_is_allowlisted(path):
        raise ValueError(f"source path is not on the release allowlist: {path}")


def normalized_payload(repository: Path, path: str) -> bytes:
    validate_release_path(path)
    root = repository.resolve(strict=True)
    source = root / path
    if source.is_symlink():
        raise ValueError(f"tracked symlink is forbidden: {path}")
    metadata = source.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"tracked release input is not a regular file: {path}")
    resolved = source.resolve(strict=True)
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"tracked release input escapes repository: {path}")
    if metadata.st_size > MAX_SOURCE_FILE_BYTES:
        raise ValueError(f"source file exceeds size limit: {path}")
    payload = source.read_bytes()
    if source_path_is_binary(path):
        return payload
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"release text file is not valid UTF-8: {path}") from error
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if path.endswith(".bat"):
        text = text.replace("\n", "\r\n")
    return text.encode("utf-8")


def build_manifest(
    entries: tuple[ManifestEntry, ...],
    *,
    version: str,
    commit: str,
    source_date_epoch: int,
) -> bytes:
    document = {
        "schema_version": "operations-ai-portable-release/v1",
        "version": version,
        "source_commit": commit,
        "source_date_epoch": source_date_epoch,
        "files": [
            asdict(entry)
            for entry in sorted(
                entries,
                key=lambda value: value.path.encode("utf-8"),
            )
        ],
    }
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def fixed_zip_datetime(source_date_epoch: int) -> tuple[int, int, int, int, int, int]:
    if source_date_epoch < ZIP_MINIMUM_EPOCH:
        raise ValueError("SOURCE_DATE_EPOCH must be on or after 1980-01-01")
    value = datetime.fromtimestamp(source_date_epoch, tz=timezone.utc)
    return (value.year, value.month, value.day, value.hour, value.minute, value.second)


def _manifest_payload(
    entries: tuple[ManifestEntry, ...],
    *,
    version: str,
    commit: str,
    source_date_epoch: int,
) -> tuple[bytes, ManifestEntry]:
    manifest_entry = ManifestEntry(
        path="release-manifest.json",
        size=0,
        mode=0o644,
        sha256=None,
    )
    for _ in range(10):
        payload = build_manifest(
            (*entries, manifest_entry),
            version=version,
            commit=commit,
            source_date_epoch=source_date_epoch,
        )
        updated = ManifestEntry(
            path=manifest_entry.path,
            size=len(payload),
            mode=manifest_entry.mode,
            sha256=None,
        )
        if updated == manifest_entry:
            return payload, manifest_entry
        manifest_entry = updated
    raise RuntimeError("release manifest size did not converge")


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _write_zip(
    path: Path,
    payloads: tuple[_Payload, ...],
    *,
    timestamp: tuple[int, int, int, int, int, int],
) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("wb") as raw:
            with zipfile.ZipFile(
                raw,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                for payload in sorted(
                    payloads,
                    key=lambda value: value.path.encode("utf-8"),
                ):
                    info = zipfile.ZipInfo(payload.path, timestamp)
                    info.create_system = 3
                    info.external_attr = (payload.mode & 0xFFFF) << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(
                        info,
                        payload.content,
                        compress_type=zipfile.ZIP_DEFLATED,
                        compresslevel=9,
                    )
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def build_portable_release(
    *,
    repository: Path,
    output_dir: Path,
    version: str,
    source_date_epoch: int,
) -> PortableBuildResult:
    if not SEMANTIC_VERSION.fullmatch(version):
        raise ValueError("version must be a numeric semantic version")
    timestamp = fixed_zip_datetime(source_date_epoch)
    repository = repository.resolve(strict=True)
    dirty = _git(
        repository,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    if dirty:
        raise ValueError("tracked worktree must be clean before release")
    commit = _git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    paths = tracked_paths(repository)
    modes = _tracked_modes(repository)
    payloads: list[_Payload] = []
    archive_keys: dict[str, str] = {}
    for path in paths:
        index_mode = modes[path]
        if index_mode == 0o120000:
            raise ValueError(f"tracked symlink is forbidden: {path}")
        content = normalized_payload(repository, path)
        archive_path = PORTABLE_ROOT_MAPPING.get(path, path)
        collision_key = archive_path.casefold()
        previous = archive_keys.get(collision_key)
        if previous is not None:
            raise ValueError(
                f"release archive path collision: {previous} and {archive_path}"
            )
        archive_keys[collision_key] = archive_path
        mode = 0o755 if index_mode == 0o100755 else 0o644
        payloads.append(_Payload(path=archive_path, content=content, mode=mode))
    entries = tuple(
        ManifestEntry(
            path=payload.path,
            size=len(payload.content),
            mode=payload.mode,
            sha256=sha256(payload.content).hexdigest(),
        )
        for payload in payloads
    )
    manifest, manifest_entry = _manifest_payload(
        entries,
        version=version,
        commit=commit,
        source_date_epoch=source_date_epoch,
    )
    payloads.append(
        _Payload(
            path=manifest_entry.path,
            content=manifest,
            mode=manifest_entry.mode,
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"operations-ai-portable-{version}.zip"
    _write_zip(zip_path, tuple(payloads), timestamp=timestamp)
    digest = sha256(zip_path.read_bytes()).hexdigest()
    _atomic_write(output_dir / "release-manifest.json", manifest)
    _atomic_write(
        output_dir / "checksums.txt",
        f"{digest}  {zip_path.name}\n".encode("utf-8"),
    )
    return PortableBuildResult(
        zip_path=zip_path,
        sha256=digest,
        file_count=len(payloads),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-date-epoch", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_portable_release(
            repository=args.repository,
            output_dir=args.output_dir,
            version=args.version,
            source_date_epoch=args.source_date_epoch,
        )
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"portable_build=failed: {error}", file=sys.stderr)
        return 1
    print(f"portable_zip={result.zip_path}")
    print(f"portable_sha256={result.sha256}")
    print(f"portable_file_count={result.file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

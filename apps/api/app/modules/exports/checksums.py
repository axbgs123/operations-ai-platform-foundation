import hashlib
import hmac
import json
from pathlib import PurePosixPath
import re
import unicodedata
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def validate_archive_path(path: str) -> str:
    if not path or len(path) > 512:
        raise ValueError("archive path is empty or too long")
    if (
        path.startswith(("/", "\\"))
        or "\\" in path
        or "%" in path
        or "\x00" in path
        or unicodedata.normalize("NFKC", path) != path
    ):
        raise ValueError("archive path is unsafe")
    if re.match(r"^[A-Za-z]:", path):
        raise ValueError("archive path is unsafe")
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("archive path is unsafe")
    if path not in {"manifest.json", "data.json"} and not path.startswith(
        ("assets/", "knowledge/")
    ):
        raise ValueError("archive path is outside the fixed layout")
    return path


class ChecksumEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: StrictStr = Field(min_length=1, max_length=512)
    sha256: StrictStr = Field(min_length=64, max_length=64)
    byte_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_entry(self) -> "ChecksumEntry":
        validate_archive_path(self.path)
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("checksum must be lowercase SHA-256")
        return self


class ChecksumManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["sha256"]
    files: tuple[ChecksumEntry, ...]

    @model_validator(mode="after")
    def require_unique_paths(self) -> "ChecksumManifest":
        paths = [entry.path for entry in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate checksum path")
        folded = [path.casefold() for path in paths]
        if len(folded) != len(set(folded)):
            raise ValueError("duplicate checksum path by case")
        return self


def build_checksum_manifest(files: dict[str, bytes]) -> ChecksumManifest:
    return ChecksumManifest(
        algorithm="sha256",
        files=tuple(
            ChecksumEntry(
                path=path,
                sha256=hashlib.sha256(content).hexdigest(),
                byte_count=len(content),
            )
            for path, content in sorted(files.items())
        ),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key in checksums")
        result[key] = value
    return result


def parse_checksum_manifest(raw: bytes) -> ChecksumManifest:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
        return ChecksumManifest.model_validate(payload)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ) as error:
        raise ValueError("invalid checksums manifest") from error


def verify_checksums(
    files: dict[str, bytes],
    manifest: ChecksumManifest,
) -> None:
    declared = {entry.path: entry for entry in manifest.files}
    actual_paths = set(files)
    declared_paths = set(declared)
    missing = sorted(declared_paths - actual_paths)
    if missing:
        raise ValueError(f"checksum file missing: {missing[0]}")
    undeclared = sorted(actual_paths - declared_paths)
    if undeclared:
        raise ValueError(f"checksum file undeclared: {undeclared[0]}")
    for path in sorted(actual_paths):
        validate_archive_path(path)
        content = files[path]
        entry = declared[path]
        if len(content) != entry.byte_count:
            raise ValueError(f"checksum byte count mismatch: {path}")
        if not hmac.compare_digest(
            hashlib.sha256(content).hexdigest(),
            entry.sha256,
        ):
            raise ValueError(f"checksum mismatch: {path}")

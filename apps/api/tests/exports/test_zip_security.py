import hashlib
from io import BytesIO
import json
import stat
import struct
import warnings
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest

from app.modules.exports.checksums import (
    ChecksumEntry,
    ChecksumManifest,
    build_checksum_manifest,
    verify_checksums,
)
from app.modules.exports.zip_restore import (
    ArchiveLimits,
    BackupArchiveError,
    read_verified_backup_zip,
)


pytestmark = pytest.mark.security


def test_checksums_require_every_declared_file_and_reject_tampering() -> None:
    files = {
        "manifest.json": b'{"schema_version":"1.0.0"}',
        "data.json": b"{}",
        "assets/item.bin": b"synthetic",
    }
    checksums = ChecksumManifest(
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
    verify_checksums(files, checksums)

    with pytest.raises(ValueError, match="assets/item.bin"):
        verify_checksums(
            {**files, "assets/item.bin": b"Synthetic"},
            checksums,
        )
    with pytest.raises(ValueError, match="data.json"):
        verify_checksums(
            {key: value for key, value in files.items() if key != "data.json"},
            checksums,
        )
    with pytest.raises(ValueError, match="undeclared.json"):
        verify_checksums(
            {**files, "undeclared.json": json.dumps({"safe": True}).encode()},
            checksums,
        )


def test_checksum_manifest_rejects_duplicate_or_unsafe_paths() -> None:
    digest = hashlib.sha256(b"safe").hexdigest()
    duplicate = {
        "algorithm": "sha256",
        "files": [
            {"path": "data.json", "sha256": digest, "byte_count": 4},
            {"path": "data.json", "sha256": digest, "byte_count": 4},
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        ChecksumManifest.model_validate(duplicate)
    for unsafe in (
        "../escape",
        "/absolute",
        "C:/windows",
        r"assets\\..\\escape",
        "",
        "assets/%2e%2e/escape",
    ):
        with pytest.raises(ValueError):
            ChecksumEntry(path=unsafe, sha256=digest, byte_count=4)


def _manifest_json() -> bytes:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "product_version": "0.1.0",
            "exported_at": "2026-07-26T12:00:00Z",
            "workspace": {
                "source_id": "00000000-0000-4000-8000-000000000001",
                "name": "合成安全测试",
            },
            "records": [],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _archive(
    business_files: dict[str, bytes] | None = None,
    *,
    extra_files: dict[str, bytes] | None = None,
    compression: int = ZIP_STORED,
) -> bytes:
    data = _manifest_json()
    protected = {
        "manifest.json": data,
        "data.json": data,
        **(business_files or {}),
    }
    checksums = json.dumps(
        build_checksum_manifest(protected).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w", compression=compression) as archive:
        for path, content in (
            {**protected, "checksums.json": checksums, **(extra_files or {})}
        ).items():
            archive.writestr(path, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "../escape",
        "/absolute",
        "C:/windows",
        r"assets\\..\\escape",
        "assets/%2e%2e/escape",
        "assets/．．/escape",
    ],
)
def test_archive_rejects_path_traversal_and_unicode_confusion(
    unsafe_path: str,
) -> None:
    payload = _archive(extra_files={unsafe_path: b"synthetic"})
    with pytest.raises(BackupArchiveError) as captured:
        read_verified_backup_zip(payload)
    assert captured.value.code == "BACKUP_ARCHIVE_UNSAFE"
    assert "synthetic" not in str(captured.value)


def test_archive_rejects_duplicate_case_collision_and_special_files() -> None:
    output = BytesIO()
    data = _manifest_json()
    checksums = json.dumps(
        build_checksum_manifest(
            {"manifest.json": data, "data.json": data}
        ).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", data)
            archive.writestr("data.json", data)
            archive.writestr("checksums.json", checksums)
            archive.writestr("assets/DUP.bin", b"one")
            archive.writestr("assets/dup.bin", b"two")
    with pytest.raises(BackupArchiveError, match="duplicate"):
        read_verified_backup_zip(output.getvalue())

    symlink_output = BytesIO()
    with ZipFile(symlink_output, "w") as archive:
        for path, content in {
            "manifest.json": data,
            "data.json": data,
            "checksums.json": checksums,
        }.items():
            archive.writestr(path, content)
        link = ZipInfo("assets/link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"target")
    with pytest.raises(BackupArchiveError, match="special"):
        read_verified_backup_zip(symlink_output.getvalue())


def test_archive_enforces_upload_count_size_total_and_compression_limits() -> None:
    payload = _archive(
        {"assets/large.bin": b"A" * 1024},
        compression=ZIP_DEFLATED,
    )
    cases = [
        ArchiveLimits(
            max_upload_bytes=len(payload) - 1,
            max_files=20,
            max_file_bytes=4096,
            max_total_bytes=8192,
            max_compression_ratio=500,
        ),
        ArchiveLimits(
            max_upload_bytes=len(payload) + 1,
            max_files=3,
            max_file_bytes=4096,
            max_total_bytes=8192,
            max_compression_ratio=500,
        ),
        ArchiveLimits(
            max_upload_bytes=len(payload) + 1,
            max_files=20,
            max_file_bytes=512,
            max_total_bytes=8192,
            max_compression_ratio=500,
        ),
        ArchiveLimits(
            max_upload_bytes=len(payload) + 1,
            max_files=20,
            max_file_bytes=4096,
            max_total_bytes=512,
            max_compression_ratio=500,
        ),
        ArchiveLimits(
            max_upload_bytes=len(payload) + 1,
            max_files=20,
            max_file_bytes=4096,
            max_total_bytes=8192,
            max_compression_ratio=2,
        ),
    ]
    for limits in cases:
        with pytest.raises(BackupArchiveError) as captured:
            read_verified_backup_zip(payload, limits=limits)
        assert captured.value.code == "BACKUP_ARCHIVE_UNSAFE"


def test_archive_rejects_nested_encrypted_crc_broken_and_truncated_zip() -> None:
    nested = _archive({"assets/nested.zip": _archive()})
    with pytest.raises(BackupArchiveError, match="nested"):
        read_verified_backup_zip(nested)

    encrypted = bytearray(_archive())
    local = encrypted.index(b"PK\x03\x04")
    central = encrypted.index(b"PK\x01\x02")
    local_flags = struct.unpack_from("<H", encrypted, local + 6)[0] | 1
    central_flags = struct.unpack_from("<H", encrypted, central + 8)[0] | 1
    struct.pack_into("<H", encrypted, local + 6, local_flags)
    struct.pack_into("<H", encrypted, central + 8, central_flags)
    with pytest.raises(BackupArchiveError, match="encrypted"):
        read_verified_backup_zip(bytes(encrypted))

    crc_broken = bytearray(
        _archive({"assets/marker.bin": b"UNIQUE_CRC_MARKER"})
    )
    marker = crc_broken.index(b"UNIQUE_CRC_MARKER")
    crc_broken[marker] ^= 1
    with pytest.raises(BackupArchiveError):
        read_verified_backup_zip(bytes(crc_broken))
    with pytest.raises(BackupArchiveError):
        read_verified_backup_zip(_archive()[:-12])


def test_archive_rejects_undeclared_tampered_or_invalid_json_contracts() -> None:
    with pytest.raises(BackupArchiveError) as undeclared:
        read_verified_backup_zip(
            _archive(extra_files={"assets/undeclared.bin": b"synthetic"})
        )
    assert undeclared.value.code == "BACKUP_CHECKSUM_MISMATCH"

    tampered = bytearray(_archive({"assets/item.bin": b"UNIQUE_TAMPER"}))
    marker = tampered.index(b"UNIQUE_TAMPER")
    tampered[marker] ^= 1
    with pytest.raises(BackupArchiveError):
        read_verified_backup_zip(bytes(tampered))

    duplicate_json = _archive()
    with ZipFile(BytesIO(duplicate_json)) as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["data.json"] = members["data.json"].replace(
        b'{"exported_at"',
        b'{"schema_version":"1.0.0","exported_at"',
        1,
    )
    output = BytesIO()
    protected = {
        key: value for key, value in members.items() if key != "checksums.json"
    }
    members["checksums.json"] = json.dumps(
        build_checksum_manifest(protected).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    with ZipFile(output, "w") as archive:
        for path, content in members.items():
            archive.writestr(path, content)
    with pytest.raises(BackupArchiveError) as duplicate:
        read_verified_backup_zip(output.getvalue())
    assert duplicate.value.code == "BACKUP_REFERENCE_INVALID"

    unsupported_data = _manifest_json().replace(b'"1.0.0"', b'"9.9.9"', 1)
    unsupported = _archive()
    with ZipFile(BytesIO(unsupported)) as source:
        unsupported_members = {
            name: source.read(name) for name in source.namelist()
        }
    unsupported_members["manifest.json"] = unsupported_data
    unsupported_members["data.json"] = unsupported_data
    protected = {
        key: value
        for key, value in unsupported_members.items()
        if key != "checksums.json"
    }
    unsupported_members["checksums.json"] = json.dumps(
        build_checksum_manifest(protected).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for path, content in unsupported_members.items():
            archive.writestr(path, content)
    with pytest.raises(BackupArchiveError) as version:
        read_verified_backup_zip(output.getvalue())
    assert version.value.code == "BACKUP_SCHEMA_UNSUPPORTED"

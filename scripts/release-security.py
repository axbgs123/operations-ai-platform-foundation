#!/usr/bin/env python3
"""Deterministic, offline release-security checks for synthetic project inputs."""

from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tomllib
import unicodedata
import zipfile
import yaml

from release_policy import (
    MAX_SOURCE_FILE_BYTES,
    portable_executable_is_allowed,
    release_path_forbidden_reason,
    source_path_is_allowlisted,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"^[0-9a-f]{40}$")
MARKDOWN_LINK = re.compile(r"!?\[[^]]*\]\(([^)]+)\)")
SHELL_BLOCK = re.compile(r"```(?:bash|sh)\n(.*?)```", re.DOTALL)


def fail(label: str, problems: list[str]) -> int:
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{label}=failed")
    return 1


def verify_artifact(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    if not root.is_dir():
        return fail("release_artifact", ["artifact directory is missing"])
    allowed = {
        "extension": {
            "manifest.json", "background.js", "content.js", "popup.html", "popup.js",
            "build-metadata.js", "supported-pages.json", "PRIVACY.md", "sbom.spdx.json",
            "release-manifest.json",
        }
    }[args.kind]
    forbidden_parts = {"node_modules", ".env", "test-results", "screenshots", "__pycache__"}
    problems: list[str] = []
    asset_pattern = re.compile(r"assets/[A-Za-z0-9._-]+\.js$")
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            problems.append(f"symlink is forbidden in release artifact: {relative}")
            continue
        if any(part in forbidden_parts for part in path.parts) or path.suffix in {".map", ".log"}:
            problems.append(f"forbidden release artifact: {relative}")
            continue
        if ("/" not in relative and relative not in allowed) or ("/" in relative and not asset_pattern.fullmatch(relative)):
            problems.append(f"artifact not on allowlist: {relative}")
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"(?:sk-[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]{20,}|BEGIN .*PRIVATE KEY)", content):
            problems.append(f"sensitive material in release artifact: {relative}")
        if re.search(r"<script[^>]+src=[\"']https?://|\beval\s*\(|new Function\s*\(", content, re.I):
            problems.append(f"remote or dynamic code in release artifact: {relative}")
    release_manifest = root / "release-manifest.json"
    if not release_manifest.is_file():
        problems.append("release manifest is missing")
    else:
        try:
            entries = json.loads(release_manifest.read_text(encoding="utf-8"))["files"]
        except (KeyError, TypeError, json.JSONDecodeError):
            problems.append("release manifest is invalid")
            entries = None
        if not isinstance(entries, list):
            problems.append("release manifest is invalid")
        else:
            declared = {entry["path"]: entry for entry in entries if isinstance(entry, dict) and "path" in entry}
            actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file() or path.is_symlink()}
            missing = sorted(actual - set(declared))
            extra = sorted(set(declared) - actual)
            for item in missing:
                problems.append(f"release manifest does not cover: {item}")
            for item in extra:
                problems.append(f"release manifest references missing file: {item}")
            for item in sorted(actual & set(declared)):
                entry = declared[item]
                if item == "release-manifest.json":
                    if entry.get("sha256") is not None:
                        problems.append("release manifest self entry must use a null hash")
                elif entry.get("sha256") != sha256((root / item).read_bytes()).hexdigest():
                    problems.append(f"release manifest hash mismatch: {item}")
    return fail("release_artifact", problems) if problems else _clean("release_artifact")


def verify_ci(args: argparse.Namespace) -> int:
    text = args.path.read_text(encoding="utf-8")
    problems: list[str] = []
    if not re.search(r"^permissions:\n(?:  contents: read\n|  \{\s*contents:\s*read\s*\})", text, re.M):
        problems.append("workflow must declare top-level contents: read")
    if re.search(r":\s*write\s*(?:#.*)?$", text, re.M):
        problems.append("write permission is not permitted in CI")
    for reference in re.findall(r"^\s*-?\s*uses:\s*([^\s#]+)", text, re.M):
        if "@" not in reference:
            problems.append(f"action reference lacks immutable SHA: {reference}")
            continue
        action, revision = reference.rsplit("@", 1)
        if not SHA.fullmatch(revision):
            problems.append(f"floating action reference: {action}@{revision}")
    if "secret-scan.sh --history" in text and not re.search(
        r"uses:\s*actions/checkout@[0-9a-f]{40}(?:\s*#.*)?\n(?:.*\n){0,4}?\s*fetch-depth:\s*0\s*$",
        text,
        re.M,
    ):
        problems.append("history scanning requires checkout fetch-depth: 0")
    if not re.search(r"node-version:\s*[\"']?\d+\.\d+\.\d+[\"']?\s*$", text, re.M):
        problems.append("workflow must pin an exact Node patch version")
    if not re.search(r"uses:\s*astral-sh/setup-uv@[0-9a-f]{40}(?:\s*#.*)?\n(?:.*\n){0,5}?\s*version:\s*[\"']?\d+\.\d+\.\d+[\"']?\s*$", text, re.M):
        problems.append("workflow must pin a fixed uv version")
    for invocation in re.findall(r"^.*scripts/release-security\.py.*$", text, re.M):
        if "uv run --project apps/api python scripts/release-security.py" not in invocation:
            problems.append("release-security must run through the locked uv project")
            break
    return fail("ci_policy", problems) if problems else _clean("ci_policy")


def verify_docs(args: argparse.Namespace) -> int:
    root = args.root.resolve()
    readme = root / args.readme
    if not readme.is_file():
        return fail("docs_contract", ["README is missing"])
    problems: list[str] = []
    readme_text = readme.read_text(encoding="utf-8")
    ignored_parts = {".git", "node_modules", ".venv", "__pycache__"}
    for markdown in sorted(root.rglob("*.md")):
        if any(part in ignored_parts for part in markdown.relative_to(root).parts):
            continue
        relative_markdown = markdown.relative_to(root).as_posix()
        text = markdown.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            if not target or target.startswith(("http://", "https://", "#", "mailto:", "data:")):
                continue
            target_path = (markdown.parent / target.split("#", 1)[0]).resolve()
            if root not in target_path.parents and target_path != root:
                problems.append(f"{relative_markdown}: document link escapes repository: {raw_target}")
            elif not target_path.is_file():
                problems.append(f"{relative_markdown}: document link is missing: {target}")
            elif target_path.suffix.lower() == ".png" and not _is_valid_png(target_path.read_bytes()):
                problems.append(f"{relative_markdown}: PNG is structurally invalid: {target}")
    executed_config = False
    for block in SHELL_BLOCK.findall(readme_text):
      for command in block.splitlines():
        normalized = " ".join(command.strip().split())
        if normalized.startswith("docker compose ") and " config" in normalized:
            executed_config = True
            result = subprocess.run(command, cwd=readme.parent, shell=True, text=True, capture_output=True, check=False)
            if result.returncode != 0:
                problems.append("documented compose command failed")
    if args.require_compose_config and not executed_config:
        problems.append("README must include a runnable docker compose config command")
    return fail("docs_contract", problems) if problems else _clean("docs_contract")


def package(name: str, version: str, scope: str) -> dict[str, str]:
    identifier = re.sub(r"[^A-Za-z0-9.-]+", "-", f"{name}-{version}").strip("-")
    return {"SPDXID": f"SPDXRef-{scope}-{identifier}", "name": name, "versionInfo": version, "downloadLocation": "NOASSERTION", "licenseConcluded": "NOASSERTION", "licenseDeclared": "NOASSERTION", "filesAnalyzed": False}


def write_spdx(path: Path, name: str, packages: list[dict[str, str]], lock_content: str) -> None:
    packages = list({item["SPDXID"]: item for item in packages}.values())
    namespace = f"https://operations-ai.invalid/spdx/{name}/{sha256(lock_content.encode()).hexdigest()}"
    document = {"spdxVersion": "SPDX-2.3", "dataLicense": "CC0-1.0", "SPDXID": "SPDXRef-DOCUMENT", "name": name, "documentNamespace": namespace, "creationInfo": {"creators": ["Tool: release-security.py"], "created": "2026-07-28T00:00:00Z"}, "comment": "Scope: complete lockfile dependency inventory; not a container image SBOM.", "packages": packages, "relationships": [{"spdxElementId": "SPDXRef-DOCUMENT", "relationshipType": "DESCRIBES", "relatedSpdxElement": item["SPDXID"]} for item in packages]}
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def generate_sbom(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    api_lock_text = (ROOT / "apps/api/uv.lock").read_text(encoding="utf-8")
    api_lock = tomllib.loads(api_lock_text)
    api_packages = [package(item["name"], item["version"], "api") for item in api_lock["package"] if item.get("source", {}).get("virtual") != "."]
    lock_text = (ROOT / "pnpm-lock.yaml").read_text(encoding="utf-8")
    lock = yaml.safe_load(lock_text)
    web_packages = _web_production_closure(lock)
    write_spdx(output / "api.spdx.json", "operations-ai-api", api_packages, api_lock_text)
    write_spdx(output / "web.spdx.json", "operations-ai-web", web_packages, lock_text)
    print(f"sbom_output={output}")
    return 0


def verify_sbom(args: argparse.Namespace) -> int:
    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fail("sbom", ["SBOM is not valid JSON"])
    problems: list[str] = []
    required_document = {"spdxVersion", "dataLicense", "SPDXID", "name", "documentNamespace", "creationInfo", "packages", "relationships"}
    missing_document = sorted(required_document - document.keys()) if isinstance(document, dict) else sorted(required_document)
    if missing_document:
        problems.append(f"SBOM missing document fields: {', '.join(missing_document)}")
    elif document["spdxVersion"] != "SPDX-2.3" or document["SPDXID"] != "SPDXRef-DOCUMENT":
        problems.append("SBOM has an invalid SPDX document identity")
    packages = document.get("packages", []) if isinstance(document, dict) else []
    if not isinstance(packages, list) or not packages:
        problems.append("SBOM must contain packages")
        packages = []
    ids = [item.get("SPDXID") for item in packages if isinstance(item, dict)]
    if len(ids) != len(packages) or len(ids) != len(set(ids)):
        problems.append("SBOM package SPDXIDs must be present and unique")
    for item in packages:
        if not isinstance(item, dict) or any(not item.get(field) for field in ("name", "versionInfo", "downloadLocation", "licenseConcluded", "licenseDeclared")):
            problems.append("SBOM package has incomplete required fields")
            break
    described = {item.get("relatedSpdxElement") for item in document.get("relationships", []) if isinstance(item, dict) and item.get("spdxElementId") == "SPDXRef-DOCUMENT" and item.get("relationshipType") == "DESCRIBES"}
    if set(ids) != described:
        problems.append("SBOM document must DESCRIBE every package")
    return fail("sbom", problems) if problems else _clean("sbom")


def verify_source_release(args: argparse.Namespace) -> int:
    root = args.path.resolve()
    problems: list[str] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_symlink():
            problems.append(f"symlink is forbidden in source release: {relative.as_posix()}")
            continue
        if path.is_dir():
            continue
        if not relative.parts:
            continue
        if not source_path_is_allowlisted(relative.as_posix()):
            problems.append(f"source release path is not recursively allowlisted: {relative.as_posix()}")
    return fail("source_release", problems) if problems else _clean("source_release")


_PORTABLE_ROOT_FILES = {
    "启动运营工具-macOS.command",
    "停止运营工具-macOS.command",
    "启动运营工具-Windows.bat",
    "停止运营工具-Windows.bat",
    "使用说明.txt",
}
_PORTABLE_REQUIRED_FILES = _PORTABLE_ROOT_FILES | {
    ".env.example",
    "infra/docker/compose.yml",
    "release-manifest.json",
}
_PORTABLE_MANIFEST_FIELDS = {
    "schema_version",
    "version",
    "source_commit",
    "source_date_epoch",
    "files",
}
_PORTABLE_ENTRY_FIELDS = {"path", "size", "mode", "sha256"}


def _portable_path_problem(path: str) -> str | None:
    if (
        not path
        or "\0" in path
        or "\\" in path
        or path.startswith("/")
        or path.endswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or "//" in path
    ):
        return "unsafe archive path"
    parts = PurePosixPath(path).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return "unsafe archive path"
    reason = release_path_forbidden_reason(path)
    if reason is not None:
        return f"forbidden portable path ({reason})"
    if (
        path not in _PORTABLE_ROOT_FILES
        and path != "release-manifest.json"
        and not source_path_is_allowlisted(path)
    ):
        return "portable path is not allowlisted"
    return None


def _portable_checksum_problems(path: Path, digest: str) -> list[str]:
    checksum_path = path.parent / "checksums.txt"
    if not checksum_path.is_file():
        return ["portable checksum contract is missing"]
    try:
        checksum = checksum_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ["portable checksum contract is invalid"]
    expected = f"{digest}  {path.name}\n"
    return [] if checksum == expected else ["portable checksum does not match ZIP"]


def _portable_manifest_problems(
    *,
    archive: zipfile.ZipFile,
    infos: dict[str, zipfile.ZipInfo],
    path: Path,
) -> list[str]:
    problems: list[str] = []
    info = infos.get("release-manifest.json")
    if info is None:
        return ["portable release manifest is missing"]
    if info.flag_bits & 1:
        return ["portable release manifest is encrypted"]
    try:
        manifest_payload = archive.read(info)
        document = json.loads(manifest_payload)
    except (KeyError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
        return ["portable release manifest is invalid"]
    external_manifest = path.parent / "release-manifest.json"
    if not external_manifest.is_file():
        problems.append("external portable release manifest is missing")
    else:
        try:
            if external_manifest.read_bytes() != manifest_payload:
                problems.append("external portable release manifest does not match ZIP")
        except OSError:
            problems.append("external portable release manifest is unreadable")
    if not isinstance(document, dict) or set(document) != _PORTABLE_MANIFEST_FIELDS:
        problems.append("portable release manifest schema is invalid")
        return problems
    if document.get("schema_version") != "operations-ai-portable-release/v1":
        problems.append("portable release manifest schema version is invalid")
    if not isinstance(document.get("version"), str) or not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+",
        document["version"],
    ):
        problems.append("portable release manifest version is invalid")
    if not isinstance(document.get("source_commit"), str) or not SHA.fullmatch(
        document["source_commit"]
    ):
        problems.append("portable release manifest commit is invalid")
    if not isinstance(document.get("source_date_epoch"), int):
        problems.append("portable release manifest source epoch is invalid")
    entries = document.get("files")
    if not isinstance(entries, list):
        problems.append("portable release manifest files are invalid")
        return problems
    declared: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _PORTABLE_ENTRY_FIELDS:
            problems.append("portable release manifest entry is invalid")
            continue
        entry_path = entry.get("path")
        if not isinstance(entry_path, str):
            problems.append("portable release manifest entry path is invalid")
            continue
        if entry_path in declared:
            problems.append(f"portable release manifest repeats path: {entry_path}")
            continue
        declared[entry_path] = entry
    actual_names = set(infos)
    for name in sorted(actual_names - set(declared)):
        problems.append(f"manifest does not cover portable file: {name}")
    for name in sorted(set(declared) - actual_names):
        problems.append(f"manifest references missing portable file: {name}")
    for name in sorted(actual_names & set(declared)):
        current = infos[name]
        entry = declared[name]
        raw_mode = (current.external_attr >> 16) & 0xFFFF
        mode = raw_mode & 0o777
        if entry.get("size") != current.file_size:
            problems.append(f"portable manifest size mismatch: {name}")
        if entry.get("mode") != mode:
            problems.append(f"portable manifest mode mismatch: {name}")
        if name == "release-manifest.json":
            if entry.get("sha256") is not None:
                problems.append("portable manifest self hash must be null")
            continue
        if current.flag_bits & 1:
            continue
        try:
            payload = archive.read(current)
        except (RuntimeError, zipfile.BadZipFile):
            problems.append(f"portable file cannot be read safely: {name}")
            continue
        if entry.get("sha256") != sha256(payload).hexdigest():
            problems.append(f"portable manifest hash mismatch: {name}")
    return problems


def verify_portable_release(args: argparse.Namespace) -> int:
    path = args.path.resolve()
    if not path.is_file():
        return fail("portable_release", ["portable ZIP is missing"])
    digest = sha256(path.read_bytes()).hexdigest()
    problems = _portable_checksum_problems(path, digest)
    try:
        with zipfile.ZipFile(path) as archive:
            records = archive.infolist()
            infos: dict[str, zipfile.ZipInfo] = {}
            normalized: dict[str, str] = {}
            total_size = 0
            for info in records:
                name = info.filename
                collision_key = unicodedata.normalize("NFC", name).casefold()
                if name in infos or collision_key in normalized:
                    previous = infos.get(name)
                    previous_name = (
                        previous.filename if previous is not None else normalized[collision_key]
                    )
                    problems.append(f"colliding path in portable ZIP: {previous_name} and {name}")
                else:
                    infos[name] = info
                    normalized[collision_key] = name
                path_problem = _portable_path_problem(name)
                if path_problem is not None:
                    problems.append(f"{path_problem}: {name}")
                if info.flag_bits & 1:
                    problems.append(f"encrypted portable entry is forbidden: {name}")
                raw_mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_IFMT(raw_mode) == stat.S_IFLNK:
                    problems.append(f"symlink is forbidden in portable ZIP: {name}")
                mode = raw_mode & 0o777
                if mode & 0o111 and not portable_executable_is_allowed(name):
                    problems.append(f"unexpected executable portable file: {name}")
                if info.file_size > MAX_SOURCE_FILE_BYTES:
                    problems.append(f"portable entry exceeds size limit: {name}")
                total_size += info.file_size
            if total_size > 512 * 1024 * 1024:
                problems.append("portable ZIP uncompressed size exceeds limit")
            for required in sorted(_PORTABLE_REQUIRED_FILES - set(infos)):
                problems.append(f"missing required portable entry: {required}")
            if not any(name.startswith("apps/api/app/") for name in infos):
                problems.append("missing required portable entry: apps/api/app/**")
            if not any(name.startswith("apps/web/src/") for name in infos):
                problems.append("missing required portable entry: apps/web/src/**")
            problems.extend(
                _portable_manifest_problems(
                    archive=archive,
                    infos=infos,
                    path=path,
                )
            )
    except (OSError, zipfile.BadZipFile):
        problems.append("portable ZIP is invalid")
    return fail("portable_release", problems) if problems else _clean("portable_release")


def verify_exceptions(args: argparse.Namespace) -> int:
    try:
        document = yaml.safe_load(args.path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return fail("security_exceptions", [f"security exceptions YAML is invalid: {exc.__class__.__name__}"])
    required = {"cve", "affected_version", "impact", "mitigation", "owner", "review_date"}
    problems: list[str] = []
    if not isinstance(document, dict) or set(document) != {"exceptions"}:
        return fail("security_exceptions", ["security exceptions must be a mapping with only an exceptions key"])
    exceptions = document["exceptions"]
    if not isinstance(exceptions, list):
        return fail("security_exceptions", ["exceptions must be an explicit list"])
    for index, values in enumerate(exceptions, start=1):
        if not isinstance(values, dict):
            problems.append(f"exception {index} must be a mapping")
            continue
        unknown = sorted(set(values) - required)
        if unknown:
            problems.append(f"exception {index} has unknown field: {', '.join(unknown)}")
        missing = sorted(required - values.keys())
        if missing:
            problems.append(f"exception {index} missing fields: {', '.join(missing)}")
            continue
        invalid_types = sorted(
            key for key in required
            if (key == "review_date" and not isinstance(values[key], (str, date)))
            or (key != "review_date" and (not isinstance(values[key], str) or not values[key].strip()))
        )
        if invalid_types:
            problems.append(f"exception {index} fields must be a non-empty string (empty field or wrong type): {', '.join(invalid_types)}")
        if isinstance(values["cve"], str) and not re.fullmatch(r"CVE-\d{4}-\d{4,}", values["cve"]):
            problems.append(f"exception {index} has an invalid CVE")
        review_value = values["review_date"].isoformat() if isinstance(values["review_date"], date) else values["review_date"]
        if not isinstance(review_value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", review_value):
            problems.append(f"exception {index} has an invalid review date")
        else:
            try:
                review_date = date.fromisoformat(review_value)
            except ValueError:
                problems.append(f"exception {index} has an invalid review date")
            else:
                if review_date < date.today():
                    problems.append(f"exception {index} has an expired review date")
    return fail("security_exceptions", problems) if problems else _clean("security_exceptions")


def verify_demo_screenshot(args: argparse.Namespace) -> int:
    data = args.path.read_bytes() if args.path.is_file() else b""
    problems: list[str] = []
    if not _is_valid_png(data):
        problems.append("demo screenshot must be a structurally valid PNG")
    if any(marker in data.lower() for marker in (b"failed to fetch", b"internal server error", b"error page")):
        problems.append("demo screenshot contains an error-page marker")
    provenance_path = args.metadata or args.path.with_suffix(".provenance.json")
    if not provenance_path.is_file():
        problems.append("demo screenshot capture provenance is missing")
    else:
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            problems.append("demo screenshot capture provenance is invalid")
        else:
            required = {"schema", "image", "sha256", "capture"}
            if not isinstance(provenance, dict) or set(provenance) != required:
                problems.append("demo screenshot capture provenance has an invalid schema")
            elif provenance["schema"] != "operations-ai-demo-screenshot/v1" or provenance["image"] != args.path.name or provenance["sha256"] != sha256(data).hexdigest():
                problems.append("demo screenshot capture provenance does not match image")
            elif not isinstance(provenance["capture"], dict) or provenance["capture"].get("mode") != "isolated-compose-mock" or provenance["capture"].get("route") != "/demo" or provenance["capture"].get("synthetic") is not True:
                problems.append("demo screenshot capture provenance is not a synthetic /demo capture")
    return fail("demo_screenshot", problems) if problems else _clean("demo_screenshot")


def _web_production_closure(lock: dict[object, object]) -> list[dict[str, str]]:
    """Follow Web production dependencies and runtime optional dependencies."""
    import collections

    importers = lock.get("importers", {})
    snapshots = lock.get("snapshots", {})
    resolved_packages = lock.get("packages", {})
    if not isinstance(importers, dict) or not isinstance(snapshots, dict) or not isinstance(resolved_packages, dict):
        raise ValueError("pnpm lock is missing importer or snapshot data")
    nodes = dict(resolved_packages)
    nodes.update(snapshots)
    web = importers.get("apps/web", {})
    if not isinstance(web, dict) or not isinstance(web.get("dependencies"), dict):
        raise ValueError("pnpm lock is missing apps/web production dependencies")

    def resolve(name: str, value: object) -> tuple[str, str] | None:
        version = value.get("version") if isinstance(value, dict) else value
        if not isinstance(version, str) or version.startswith(("link:", "file:")):
            return None
        exact = version.split("(", 1)[0]
        candidates = (
            [key for key in nodes if key == f"{name}@{version}"]
            + [key for key in nodes if key.startswith(f"{name}@{exact}(")]
            + [key for key in nodes if key == f"{name}@{exact}"]
        )
        if not candidates:
            return None
        return candidates[0], exact

    queue: collections.deque[tuple[str, str, str]] = collections.deque()
    for name, value in web["dependencies"].items():
        resolved = resolve(name, value)
        if resolved:
            queue.append((name, resolved[1], resolved[0]))
    # The web app's workspace dependency has a production edge to openapi-fetch.
    shared = json.loads((ROOT / "packages/shared-schemas/package.json").read_text(encoding="utf-8"))
    for name, version in shared.get("dependencies", {}).items():
        resolved = resolve(name, version)
        if resolved:
            queue.append((name, resolved[1], resolved[0]))

    seen: set[str] = set()
    packages: list[dict[str, str]] = []
    while queue:
        name, version, snapshot_key = queue.popleft()
        if snapshot_key in seen:
            continue
        seen.add(snapshot_key)
        packages.append(package(name, version, "web"))
        snapshot = nodes[snapshot_key]
        if not isinstance(snapshot, dict):
            continue
        dependencies = snapshot.get("dependencies", {})
        optional_dependencies = snapshot.get("optionalDependencies", {})
        dependency_sets = [dependencies]
        if isinstance(optional_dependencies, dict):
            dependency_sets.append(optional_dependencies)
        for dependency_set in dependency_sets:
            if not isinstance(dependency_set, dict):
                continue
            for dependency, dependency_value in dependency_set.items():
                # Next lists its test harness as optional; it is not part of a Web runtime image.
                if dependency == "@playwright/test":
                    continue
                resolved = resolve(dependency, dependency_value)
                if resolved:
                    queue.append((dependency, resolved[1], resolved[0]))
    return packages


def _is_valid_png(data: bytes) -> bool:
    """Validate PNG framing and CRCs without treating a magic header as a decoded image."""
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    position = 8
    saw_ihdr = False
    while position < len(data):
        if position + 12 > len(data):
            return False
        length = int.from_bytes(data[position:position + 4], "big")
        chunk_type = data[position + 4:position + 8]
        end = position + 12 + length
        if end > len(data):
            return False
        chunk = data[position + 8:position + 8 + length]
        expected_crc = int.from_bytes(data[position + 8 + length:end], "big")
        import zlib
        if zlib.crc32(chunk_type + chunk) & 0xFFFFFFFF != expected_crc:
            return False
        if chunk_type == b"IHDR":
            if saw_ihdr or length != 13 or int.from_bytes(chunk[:4], "big") == 0 or int.from_bytes(chunk[4:8], "big") == 0:
                return False
            saw_ihdr = True
        if chunk_type == b"IEND":
            return saw_ihdr and length == 0 and end == len(data)
        position = end
    return False


def _clean(label: str) -> int:
    print(f"{label}=clean")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    artifact = commands.add_parser("verify-artifact")
    artifact.add_argument("--kind", choices=["extension"], required=True)
    artifact.add_argument("--path", type=Path, required=True)
    artifact.set_defaults(handler=verify_artifact)
    ci = commands.add_parser("verify-ci")
    ci.add_argument("--path", type=Path, required=True)
    ci.set_defaults(handler=verify_ci)
    docs = commands.add_parser("verify-docs")
    docs.add_argument("--root", type=Path, required=True)
    docs.add_argument("--readme", default="README.md")
    docs.add_argument("--require-compose-config", action="store_true")
    docs.set_defaults(handler=verify_docs)
    sbom = commands.add_parser("generate-sbom")
    sbom.add_argument("--output", type=Path, required=True)
    sbom.set_defaults(handler=generate_sbom)
    verify_sbom_parser = commands.add_parser("verify-sbom")
    verify_sbom_parser.add_argument("--path", type=Path, required=True)
    verify_sbom_parser.set_defaults(handler=verify_sbom)
    source_release = commands.add_parser("verify-source-release")
    source_release.add_argument("--path", type=Path, required=True)
    source_release.set_defaults(handler=verify_source_release)
    portable_release = commands.add_parser("verify-portable-release")
    portable_release.add_argument("--path", type=Path, required=True)
    portable_release.set_defaults(handler=verify_portable_release)
    exceptions = commands.add_parser("verify-exceptions")
    exceptions.add_argument("--path", type=Path, required=True)
    exceptions.set_defaults(handler=verify_exceptions)
    screenshot = commands.add_parser("verify-demo-screenshot")
    screenshot.add_argument("--path", type=Path, required=True)
    screenshot.add_argument("--metadata", type=Path)
    screenshot.set_defaults(handler=verify_demo_screenshot)
    args = parser.parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

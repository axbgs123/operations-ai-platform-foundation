from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[4]
SECURITY_TOOL = REPO_ROOT / "scripts" / "release-security.py"


def run_tool(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SECURITY_TOOL), *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_checker_rejects_a_private_file_in_an_extension_artifact(tmp_path: Path) -> None:
    """Removing release-file checks would allow private material to ship."""
    artifact = tmp_path / "extension"
    artifact.mkdir()
    (artifact / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
    (artifact / "private-notes.txt").write_text("synthetic only", encoding="utf-8")

    result = run_tool("verify-artifact", "--kind", "extension", "--path", str(artifact))

    assert result.returncode == 1
    assert "release_artifact=failed" in result.stdout
    assert "private-notes.txt" in result.stderr


def test_history_scan_rejects_a_secret_removed_from_the_current_tree(tmp_path: Path) -> None:
    """Changing the scanner to inspect HEAD only would miss this synthetic history."""
    repo = tmp_path / "history"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "synthetic@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Synthetic Test"], check=True)
    synthetic_secret = "sk-" + "A" * 20
    (repo / "removed.txt").write_text(f"synthetic_key={synthetic_secret}", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "removed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "synthetic historical fixture"], check=True)
    (repo / "removed.txt").unlink()
    subprocess.run(["git", "-C", str(repo), "add", "-u"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "remove synthetic fixture"], check=True)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo), "--history"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout.strip() == "secret_scan=failed"
    assert "sk-" not in result.stdout + result.stderr


def test_history_scan_accepts_a_clean_full_history_and_rejects_an_untracked_current_secret(tmp_path: Path) -> None:
    """A scanner that only inspects Git-tracked files misses a leaked local release input."""
    repo = tmp_path / "working-tree"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "synthetic@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Synthetic Test"], check=True)
    (repo / "README.md").write_text("clean", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "clean synthetic fixture"], check=True)

    clean = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo), "--history"], check=False, capture_output=True, text=True)
    assert clean.returncode == 0
    (repo / "untracked.txt").write_text("key=" + "sk-" + "B" * 20, encoding="utf-8")
    leaked = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo)], check=False, capture_output=True, text=True)
    assert leaked.returncode == 1
    assert leaked.stdout.strip() == "secret_scan=failed"


def test_sbom_generator_emits_parseable_documents_for_all_release_targets(tmp_path: Path) -> None:
    """Source SBOM generation must not pretend that it inspected final images."""
    output = tmp_path / "sbom"

    result = run_tool("generate-sbom", "--output", str(output))

    assert result.returncode == 0, result.stderr
    expected = {"api.spdx.json", "web.spdx.json"}
    assert {path.name for path in output.iterdir()} == expected
    for path in output.iterdir():
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["spdxVersion"] == "SPDX-2.3"
        assert document["comment"] == "Scope: complete lockfile dependency inventory; not a container image SBOM."
        assert document["packages"]
        assert all(not any(symbol in package["versionInfo"] for symbol in "<>=^~*") for package in document["packages"])


def test_ci_policy_requires_a_full_checkout_before_history_scanning() -> None:
    """A shallow checkout makes an all-history secret scan falsely reassuring."""
    result = run_tool("verify-ci", "--path", REPO_ROOT / ".github/workflows/ci.yml")

    assert result.returncode == 0, result.stderr


def test_ci_policy_rejects_a_pinned_checkout_without_fetch_depth_zero(tmp_path: Path) -> None:
    """A SHA pin alone is insufficient when the workflow claims an all-history scan."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        """permissions:\n  contents: read\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683\n      - run: bash scripts/secret-scan.sh --history\n""",
        encoding="utf-8",
    )

    result = run_tool("verify-ci", "--path", str(workflow))

    assert result.returncode == 1
    assert "fetch-depth: 0" in result.stderr


def test_release_source_allowlist_rejects_a_backup_file(tmp_path: Path) -> None:
    """Removing source-release allowlists would ship accidental backups."""
    release = tmp_path / "release"
    release.mkdir()
    (release / "README.md").write_text("synthetic", encoding="utf-8")
    (release / "workspace-backup.zip").write_text("synthetic", encoding="utf-8")

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 1
    assert "source_release=failed" in result.stdout
    assert "workspace-backup.zip" in result.stderr


def test_release_source_requires_file_level_review_for_binary_test_assets(
    tmp_path: Path,
) -> None:
    """A new binary fixture must not bypass the asset provenance inventory."""
    release = tmp_path / "release"
    fixture = release / "apps/api/tests/fixtures/imports/customer-export.xlsx"
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"synthetic but not reviewed")

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 1
    assert "customer-export.xlsx" in result.stderr


def test_release_source_allowlist_accepts_exact_gitleaks_fingerprint_baseline(
    tmp_path: Path,
) -> None:
    """The reviewed exact-fingerprint history baseline belongs in source releases."""
    release = tmp_path / "release"
    release.mkdir()
    (release / ".gitleaksignore").write_text(
        "0" * 40 + ":apps/api/tests/example.py:generic-api-key:1\n",
        encoding="utf-8",
    )

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 0, result.stderr


def test_extension_artifact_rejects_nested_private_content_and_symlinks(tmp_path: Path) -> None:
    """A recursive allowlist must not be bypassed below an assets directory."""
    artifact = tmp_path / "extension"
    (artifact / "assets").mkdir(parents=True)
    (artifact / "manifest.json").write_text('{"manifest_version": 3}', encoding="utf-8")
    (artifact / "assets" / "private.txt").write_text("synthetic", encoding="utf-8")
    (artifact / "linked.txt").symlink_to(artifact / "assets" / "private.txt")

    result = run_tool("verify-artifact", "--kind", "extension", "--path", str(artifact))

    assert result.returncode == 1
    assert "private.txt" in result.stderr
    assert "symlink" in result.stderr


def test_readme_contract_requires_and_executes_a_compose_config_command() -> None:
    """A README quick start without a runnable Compose validation is incomplete."""
    result = run_tool("verify-docs", "--root", REPO_ROOT, "--readme", "README.md", "--require-compose-config")

    assert result.returncode == 0, result.stderr


def test_demo_screenshot_verifier_rejects_an_error_page_png(tmp_path: Path) -> None:
    """A fetch failure must never be presented as a current product screenshot."""
    screenshot = tmp_path / "demo.png"
    screenshot.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic Failed to fetch")

    result = run_tool("verify-demo-screenshot", "--path", str(screenshot))

    assert result.returncode == 1
    assert "demo_screenshot=failed" in result.stdout
    assert "error-page marker" in result.stderr


def test_security_exception_verifier_rejects_an_unowned_exception(tmp_path: Path) -> None:
    """An exception without accountable mitigation must not weaken a release gate."""
    exception_file = tmp_path / "exceptions.yml"
    exception_file.write_text(
        "exceptions:\n  - cve: CVE-2026-0001\n    affected_version: 1.2.3\n",
        encoding="utf-8",
    )

    result = run_tool("verify-exceptions", "--path", str(exception_file))

    assert result.returncode == 1
    assert "security_exceptions=failed" in result.stdout


def test_declared_empty_security_exceptions_are_an_explicit_clean_state() -> None:
    """A documented empty exception list must not fail because of explanatory comments."""
    result = run_tool("verify-exceptions", "--path", REPO_ROOT / ".github/security-exceptions.yml")

    assert result.returncode == 0, result.stderr


def test_ci_policy_verifier_rejects_a_floating_action_and_write_permission(tmp_path: Path) -> None:
    """Changing CI to a mutable action or write token must fail before release."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text(
        """name: synthetic\npermissions:\n  contents: write\njobs:\n  check:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n""",
        encoding="utf-8",
    )

    result = run_tool("verify-ci", "--path", str(workflow))

    assert result.returncode == 1
    assert "ci_policy=failed" in result.stdout
    assert "floating action reference" in result.stderr
    assert "write permission" in result.stderr


def test_document_verifier_runs_the_compose_command_and_resolves_document_links(tmp_path: Path) -> None:
    """Removing command execution or link validation would make this documentation gate pass."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text(
        "[existing](guide.md)\n\n```bash\ndocker compose -f compose.yml config --quiet\n```\n",
        encoding="utf-8",
    )
    (docs / "guide.md").write_text("synthetic guide", encoding="utf-8")
    (docs / "compose.yml").write_text("services: {}\n", encoding="utf-8")

    result = run_tool("verify-docs", "--root", str(docs), "--readme", "README.md")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "docs_contract=clean"


def test_secret_scan_rejects_ignored_env_lockfile_and_common_provider_credentials(tmp_path: Path) -> None:
    """Ignoring dotenv files or lockfiles would leak realistic provider credentials."""
    repo = tmp_path / "credentials"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text(".env*\n", encoding="utf-8")
    (repo / ".env.local").write_text("COOKIE=" + "session=" + "A" * 24, encoding="utf-8")
    (repo / "pnpm-lock.yaml").write_text("token=" + "npm_" + "B" * 36, encoding="utf-8")
    (repo / "providers.txt").write_text("Authorization: Bearer " + "xoxb-" + "1" * 12 + "-" + "2" * 12, encoding="utf-8")

    result = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo)], check=False, capture_output=True, text=True)

    assert result.returncode == 1
    assert result.stdout.strip() == "secret_scan=failed"
    assert "npm_" not in result.stdout + result.stderr


def test_source_release_allowlist_rejects_nested_sensitive_files(tmp_path: Path) -> None:
    """Permitting an allowlisted directory must not permit private nested payloads."""
    release = tmp_path / "release"
    (release / "docs").mkdir(parents=True)
    (release / "apps/api").mkdir(parents=True)
    (release / "docs/private.json").write_text("{}", encoding="utf-8")
    (release / "apps/api/prod-dump.sql").write_text("synthetic", encoding="utf-8")
    (release / "apps/api/.env.production").write_text("synthetic", encoding="utf-8")
    (release / "apps/api/archive.backup").write_text("synthetic", encoding="utf-8")

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 1
    for name in ("private.json", "prod-dump.sql", ".env.production", "archive.backup"):
        assert name in result.stderr


def test_sbom_covers_known_transitive_dependencies_and_has_unique_namespace(tmp_path: Path) -> None:
    """Dropping lockfile transitive dependencies makes a release inventory incomplete."""
    output = tmp_path / "sbom"
    result = run_tool("generate-sbom", "--output", str(output))
    assert result.returncode == 0, result.stderr

    api = json.loads((output / "api.spdx.json").read_text(encoding="utf-8"))
    web = json.loads((output / "web.spdx.json").read_text(encoding="utf-8"))
    assert "mako" in {package["name"] for package in api["packages"]}
    assert "scheduler" in {package["name"] for package in web["packages"]}
    assert api["documentNamespace"] != web["documentNamespace"]
    assert api["relationships"]
    assert all("licenseDeclared" in package for package in api["packages"] + web["packages"])


def test_exception_verifier_rejects_unknown_empty_and_expired_fields(tmp_path: Path) -> None:
    """Malformed exceptions must not become a quiet bypass for Critical/High gates."""
    exception_file = tmp_path / "exceptions.yml"
    exception_file.write_text(
        "exceptions:\n  - cve: CVE-2026-0001\n    affected_version: ''\n    impact: test\n    mitigation: test\n    owner: test\n    review_date: 2020-01-01\n    bypass: true\n",
        encoding="utf-8",
    )
    result = run_tool("verify-exceptions", "--path", str(exception_file))

    assert result.returncode == 1
    assert "unknown field" in result.stderr
    assert "empty field" in result.stderr
    assert "expired review date" in result.stderr


def test_extension_manifest_covers_every_packaged_file_with_matching_hash(tmp_path: Path) -> None:
    """A generated release manifest must cover itself and every distributable file."""
    artifact = tmp_path / "extension"
    artifact.mkdir()
    (artifact / "manifest.json").write_text("{}", encoding="utf-8")
    (artifact / "release-manifest.json").write_text(json.dumps({"files": []}), encoding="utf-8")
    result = run_tool("verify-artifact", "--kind", "extension", "--path", str(artifact))

    assert result.returncode == 1
    assert "release manifest does not cover" in result.stderr


def test_source_release_allowlist_rejects_a_symlink(tmp_path: Path) -> None:
    """A source archive must not carry a link that escapes its reviewed contents."""
    release = tmp_path / "release"
    release.mkdir()
    (release / "README.md").write_text("synthetic", encoding="utf-8")
    (release / "docs").mkdir()
    (release / "docs" / "linked.md").symlink_to(release / "README.md")

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 1
    assert "symlink" in result.stderr


def test_document_verifier_checks_every_markdown_file_and_decodes_pngs(tmp_path: Path) -> None:
    """Checking README alone or only PNG magic bytes would hide broken release docs."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "README.md").write_text("[guide](guide.md)\n", encoding="utf-8")
    (docs / "guide.md").write_text("![bad](bad.png)\n[missing](missing.md)\n", encoding="utf-8")
    (docs / "bad.png").write_bytes(b"\x89PNG\r\n\x1a\nnot a PNG")

    result = run_tool("verify-docs", "--root", str(docs), "--readme", "README.md")

    assert result.returncode == 1
    assert "guide.md: document link is missing: missing.md" in result.stderr
    assert "guide.md: PNG is structurally invalid: bad.png" in result.stderr


def test_generated_sboms_pass_the_project_spdx_structure_gate(tmp_path: Path) -> None:
    """A JSON-shaped SBOM without SPDX identities and relationships is not sufficient."""
    output = tmp_path / "sbom"
    assert run_tool("generate-sbom", "--output", str(output)).returncode == 0

    result = run_tool("verify-sbom", "--path", str(output / "api.spdx.json"))

    assert result.returncode == 0, result.stderr


def test_secret_scan_rejects_each_ignored_uppercase_cookie_and_authorization_value(tmp_path: Path) -> None:
    """Ignoring dotenv files must not make uppercase HTTP credentials invisible."""
    for index, key in enumerate(("COOKIE", "AUTHORIZATION")):
        repo = tmp_path / f"ignored-{index}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".gitignore").write_text(".env*\n", encoding="utf-8")
        (repo / ".env.local").write_text(f"{key}=" + "S" * 32, encoding="utf-8")

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo)],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1, key
        assert result.stdout.strip() == "secret_scan=failed"


def test_history_scan_does_not_allowlist_entire_fixture_paths(tmp_path: Path) -> None:
    """A synthetic fixture exception must be line-precise, not a permanent blind spot."""
    repo = tmp_path / "fixture-history"
    target = repo / "apps/api/app/core/rate_limit.py"
    target.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "synthetic@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Synthetic Test"], check=True)
    target.write_text("token=sk-" + "C" * 20, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "synthetic fixture path"], check=True)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo), "--history"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout.strip() == "secret_scan=failed"


def test_source_release_recursive_allowlist_rejects_unreviewed_customer_and_snapshot_json(tmp_path: Path) -> None:
    """Permitting docs/apps broadly would make sensitive JSON payloads publishable."""
    release = tmp_path / "release"
    (release / "docs").mkdir(parents=True)
    (release / "apps/api").mkdir(parents=True)
    (release / "docs/customer-data.json").write_text("{}", encoding="utf-8")
    (release / "apps/api/prod_snapshot.json").write_text("{}", encoding="utf-8")

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 1
    assert "customer-data.json" in result.stderr
    assert "prod_snapshot.json" in result.stderr


def test_extension_artifact_requires_a_release_manifest(tmp_path: Path) -> None:
    """An archive without a manifest must not bypass hash coverage checks."""
    artifact = tmp_path / "extension"
    artifact.mkdir()
    (artifact / "manifest.json").write_text("{}", encoding="utf-8")

    result = run_tool("verify-artifact", "--kind", "extension", "--path", str(artifact))

    assert result.returncode == 1
    assert "release manifest is missing" in result.stderr


def test_exception_verifier_rejects_yaml_null_collection_and_mapping_types(tmp_path: Path) -> None:
    """Regex parsing can mistake YAML nulls and collections for valid scalar controls."""
    exception_file = tmp_path / "exceptions.yml"
    exception_file.write_text(
        "exceptions:\n  - cve: CVE-2026-0001\n    affected_version: ~\n    impact: [not, scalar]\n    mitigation: {owner: nobody}\n    owner: null\n    review_date: 2026-12-31\n",
        encoding="utf-8",
    )

    result = run_tool("verify-exceptions", "--path", str(exception_file))

    assert result.returncode == 1
    assert "must be a non-empty string" in result.stderr


def test_demo_screenshot_requires_matching_capture_provenance(tmp_path: Path) -> None:
    """A structurally valid PNG alone cannot prove which synthetic UI produced it."""
    screenshot = tmp_path / "demo.png"
    screenshot.write_bytes((REPO_ROOT / "docs/assets/public-demo-synthetic-v1.png").read_bytes())

    result = run_tool("verify-demo-screenshot", "--path", str(screenshot))

    assert result.returncode == 1
    assert "capture provenance is missing" in result.stderr


def test_ci_policy_requires_exact_node_and_uv_versions() -> None:
    """Major-only runtime versions are mutable release inputs."""
    result = run_tool("verify-ci", "--path", REPO_ROOT / ".github/workflows/ci.yml")

    assert result.returncode == 0, result.stderr


def test_web_sbom_is_only_the_web_production_dependency_closure(tmp_path: Path) -> None:
    """A workspace-wide package dump wrongly labels extension/e2e/dev packages as web runtime."""
    output = tmp_path / "sbom"
    assert run_tool("generate-sbom", "--output", str(output)).returncode == 0
    packages = {item["name"] for item in json.loads((output / "web.spdx.json").read_text(encoding="utf-8"))["packages"]}

    assert {"next", "react", "react-dom", "echarts", "openapi-fetch"} <= packages
    assert "@playwright/test" not in packages
    assert "vite" not in packages
    assert any(name.startswith("@next/swc-") for name in packages)


def test_secret_scan_rejects_each_ignored_dotenv_modern_hyphenated_provider_token(tmp_path: Path) -> None:
    """Ignored dotenv files must detect modern OpenAI and Anthropic token prefixes."""
    for index, token in enumerate(("sk-proj-" + "A" * 24, "sk-ant-" + "B" * 24)):
        repo = tmp_path / f"provider-{index}"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / ".gitignore").write_text(".env*\n", encoding="utf-8")
        (repo / ".env.production").write_text(f"API_TOKEN={token}\n", encoding="utf-8")

        result = subprocess.run(
            ["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo)],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 1
        assert result.stdout.strip() == "secret_scan=failed"


def test_secret_scan_requires_the_expected_synthetic_fingerprint_at_an_allowlisted_line(tmp_path: Path) -> None:
    """Replacing a fixture line with a real-looking secret must invalidate its exception."""
    repo = tmp_path / "fingerprint"
    target = repo / "apps/api/app/core/rate_limit.py"
    target.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    target.write_text("\n" * 326 + "token=sk-proj-" + "Z" * 24 + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "secret-scan.sh"), "--repo", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert result.stdout.strip() == "secret_scan=failed"


def test_source_release_rejects_a_directory_symlink_before_directory_filtering(tmp_path: Path) -> None:
    """A symlinked directory must not disappear because Path.is_dir follows it."""
    release = tmp_path / "release"
    release.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_text("synthetic", encoding="utf-8")
    (release / "docs").symlink_to(outside, target_is_directory=True)

    result = run_tool("verify-source-release", "--path", str(release))

    assert result.returncode == 1
    assert "symlink is forbidden" in result.stderr


def test_ci_policy_rejects_any_bare_python_release_security_invocation(tmp_path: Path) -> None:
    """The strict YAML parser is only available through the locked API environment."""
    workflow = tmp_path / "ci.yml"
    workflow.write_text((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8").replace(
        "uv run --project apps/api python scripts/release-security.py verify-docs",
        "python3 scripts/release-security.py verify-docs",
        1,
    ), encoding="utf-8")

    result = run_tool("verify-ci", "--path", str(workflow))

    assert result.returncode == 1
    assert "locked uv project" in result.stderr


def test_web_sbom_includes_next_runtime_optional_dependencies_but_not_e2e(tmp_path: Path) -> None:
    """Runtime optional packages are not dev dependencies even when platform-specific."""
    output = tmp_path / "sbom"
    assert run_tool("generate-sbom", "--output", str(output)).returncode == 0
    packages = {item["name"] for item in json.loads((output / "web.spdx.json").read_text(encoding="utf-8"))["packages"]}

    assert "sharp" in packages
    assert any(name.startswith("@next/swc-") for name in packages)
    assert "@playwright/test" not in packages


def test_gitleaks_history_baseline_uses_only_exact_fingerprints() -> None:
    entries = [
        line
        for line in (REPO_ROOT / ".gitleaksignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert len(entries) == 6
    assert all(
        re.fullmatch(
            r"[0-9a-f]{40}:[A-Za-z0-9_./-]+:generic-api-key:\d+",
            entry,
        )
        for entry in entries
    )
    assert not any("*" in entry or "?" in entry for entry in entries)


def test_release_blockers_include_service_images_and_distribution_licenses() -> None:
    """The release report must not imply the security contact is the only blocker."""
    checklist = (REPO_ROOT / "docs/open-source/release-checklist.md").read_text()
    report = (
        REPO_ROOT
        / ".superpowers/sdd/2026-07-21-backup-observability-open-source-plan/task-8-report.md"
    ).read_text()

    for text in (checklist, report):
        assert "pgvector" in text
        assert "Redis/MinIO" in text
        assert "digest" in text

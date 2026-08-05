"""Shared fail-closed path policy for source and portable releases."""

from __future__ import annotations

from pathlib import PurePosixPath
import re


MAX_SOURCE_FILE_BYTES = 20 * 1024 * 1024

SOURCE_ALLOWED_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:\.dockerignore|\.env\.example|\.gitignore|\.gitleaksignore|\.node-version|LICENSE|README\.md|CONTRIBUTING\.md|CODE_OF_CONDUCT\.md|SECURITY\.md|package\.json|pnpm-lock\.yaml|pnpm-workspace\.yaml|pytest\.ini)",
        r"\.github/(?:security-exceptions\.yml|workflows/[A-Za-z0-9._-]+\.ya?ml)",
        r"\.superpowers/sdd/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+\.md",
        r"apps/api/(?:\.python-version|README\.md|alembic\.ini|pyproject\.toml|uv\.lock|app/[A-Za-z0-9_./-]+\.(?:py|ya?ml)|migrations/[A-Za-z0-9_./-]+\.(?:py|mako)|tests/[A-Za-z0-9_./-]+\.(?:py|md|csv|json))",
        r"apps/api/tests/fixtures/(?:golden-covers/template-1080x(?:1080|1440|1920)\.png|imports/(?:mock_screenshot\.png\.b64|xiaohongshu_typed\.xlsx))",
        r"apps/web/(?:\.gitignore|AGENTS\.md|CLAUDE\.md|README\.md|eslint\.config\.mjs|next\.config\.ts|package\.json|postcss\.config\.mjs|tsconfig\.json|vitest\.config\.mts|vitest\.setup\.ts|src/[A-Za-z0-9_./\[\]-]+\.(?:ts|tsx|css)|src/app/favicon\.ico)",
        r"apps/extension/(?:\.gitignore|PRIVACY\.md|eslint\.config\.mjs|manifest\.json|package\.json|supported-pages\.json|tsconfig\.json|vite\.config\.ts|vitest\.config\.ts|scripts/[A-Za-z0-9_./-]+\.mjs|src/[A-Za-z0-9_./-]+\.(?:ts|html)|tests/[A-Za-z0-9_./-]+\.(?:ts|html|d\.ts))",
        r"docs/(?:acceptance|architecture|handoff|open-source|superpowers/(?:plans|specs))/[A-Za-z0-9._/-]+\.md",
        r"docs/assets/public-demo-synthetic-v1\.(?:png|provenance\.json)",
        r"infra/docker/(?:api|web|e2e)\.Dockerfile|infra/docker/compose\.yml",
        r"packages/(?:platform-metrics|shared-schemas)/(?:package\.json|openapi\.json|scripts/[A-Za-z0-9_./-]+\.(?:ts|py)|src/[A-Za-z0-9_./-]+\.ts)",
        r"portable/[A-Za-z0-9._\-\u4e00-\u9fff]+\.(?:bat|command|txt)",
        r"scripts/[A-Za-z0-9._-]+\.(?:py|sh)",
        r"tests/e2e/(?:package\.json|[A-Za-z0-9._-]+\.(?:ts|sh))",
        r"tests/fixtures/operations_agent/cases\.json",
    )
)

_REVIEWED_VISUAL_BASELINES = frozenset(
    "tests/e2e/workbench-visual.spec.ts-snapshots/" + name
    for name in (
        "account-dashboard-darwin.png",
        "account-dashboard-error-darwin.png",
        "accounts-darwin.png",
        "analysis-queue-darwin.png",
        "columns-darwin.png",
        "content-analysis-darwin.png",
        "content-generation-darwin.png",
        "content-overview-darwin.png",
        "content-risk-darwin.png",
        "content-snapshots-darwin.png",
        "contents-darwin.png",
        "exports-darwin.png",
        "facts-darwin.png",
        "generation-edit-darwin.png",
        "generation-facts-darwin.png",
        "generation-references-darwin.png",
        "generation-review-darwin.png",
        "generation-scope-darwin.png",
        "guidance-easy-darwin.png",
        "guidance-off-darwin.png",
        "guidance-professional-darwin.png",
        "imports-darwin.png",
        "jobs-darwin.png",
        "mobile-content-detail-darwin.png",
        "mobile-guidance-darwin.png",
        "mobile-navigation-assets-darwin.png",
        "mobile-navigation-categories-darwin.png",
        "mobile-overview-darwin.png",
        "navigation-collapsed-darwin.png",
        "overview-darwin.png",
        "preflight-darwin.png",
        "public-demo-darwin.png",
        "risk-knowledge-darwin.png",
        "settings-darwin.png",
        "styles-darwin.png",
        "trash-darwin.png",
        "viewer-preflight-darwin.png",
        "viral-library-darwin.png",
    )
)

_FORBIDDEN_PARTS = frozenset(
    {
        ".git",
        ".local-state",
        ".venv",
        "__pycache__",
        "backups",
        "coverage",
        "dist",
        "logs",
        "node_modules",
        "test-results",
    }
)
_FORBIDDEN_SUFFIXES = frozenset(
    {
        ".backup",
        ".bak",
        ".cer",
        ".crt",
        ".db",
        ".dump",
        ".gz",
        ".key",
        ".log",
        ".p12",
        ".pem",
        ".pfx",
        ".sqlite",
        ".sqlite3",
        ".sql",
        ".tar",
        ".zip",
    }
)
_BINARY_SUFFIXES = frozenset({".ico", ".png", ".xlsx"})


def source_path_is_allowlisted(path: str) -> bool:
    return path in _REVIEWED_VISUAL_BASELINES or any(
        pattern.fullmatch(path) for pattern in SOURCE_ALLOWED_PATTERNS
    )


def release_path_forbidden_reason(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    if any(part in _FORBIDDEN_PARTS for part in parts):
        return "forbidden release directory"
    if len(parts) >= 2 and parts[:2] == (".superpowers", "brainstorm"):
        return "protected brainstorm path is forbidden"
    name = parts[-1] if parts else ""
    lowered = name.casefold()
    if lowered == ".env" or (lowered.startswith(".env.") and lowered != ".env.example"):
        return "environment file is forbidden"
    if PurePosixPath(lowered).suffix in _FORBIDDEN_SUFFIXES:
        return "sensitive or packaged file type is forbidden"
    return None


def source_path_is_binary(path: str) -> bool:
    return PurePosixPath(path).suffix.casefold() in _BINARY_SUFFIXES


def portable_executable_is_allowed(path: str) -> bool:
    if path in {
        "启动运营工具-macOS.command",
        "停止运营工具-macOS.command",
    }:
        return True
    return bool(
        re.fullmatch(r"scripts/[A-Za-z0-9._-]+\.sh", path)
        or re.fullmatch(r"tests/e2e/[A-Za-z0-9._-]+\.sh", path)
    )

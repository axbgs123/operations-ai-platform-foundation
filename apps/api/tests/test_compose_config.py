from pathlib import Path

import yaml


def test_postgres_18_volume_is_mounted_at_cluster_parent() -> None:
    compose_path = Path(__file__).parents[3] / "infra" / "docker" / "compose.yml"
    compose = yaml.safe_load(compose_path.read_text())

    assert (
        "postgres-data:/var/lib/postgresql"
        in compose["services"]["postgres"]["volumes"]
    )


def test_api_image_runs_as_non_root_user() -> None:
    dockerfile_path = (
        Path(__file__).parents[3] / "infra" / "docker" / "api.Dockerfile"
    )
    dockerfile = dockerfile_path.read_text()

    assert "USER appuser" in dockerfile
    assert 'CMD ["/app/.venv/bin/uvicorn"' in dockerfile
    assert 'CMD ["uv", "run"' not in dockerfile


def test_worker_executes_locked_environment_without_runtime_sync() -> None:
    compose_path = Path(__file__).parents[3] / "infra" / "docker" / "compose.yml"
    compose = yaml.safe_load(compose_path.read_text())

    assert compose["services"]["worker"]["command"][0] == "/app/.venv/bin/celery"


def test_application_images_pin_base_digest_and_drop_root() -> None:
    docker_dir = Path(__file__).parents[3] / "infra" / "docker"
    api_dockerfile = (docker_dir / "api.Dockerfile").read_text()
    web_dockerfile = (docker_dir / "web.Dockerfile").read_text()

    assert api_dockerfile.startswith("FROM python:3.12-slim@sha256:")
    assert web_dockerfile.startswith("FROM node:22-alpine@sha256:")
    assert "USER appuser" in api_dockerfile
    assert "USER nextjs" in web_dockerfile


def test_web_container_uses_only_root_workspace_and_direct_runtime() -> None:
    root = Path(__file__).parents[3]
    web_dockerfile = (root / "infra" / "docker" / "web.Dockerfile").read_text()

    assert not (root / "apps" / "web" / "pnpm-workspace.yaml").exists()
    assert "NEXT_TELEMETRY_DISABLED=1" in web_dockerfile
    assert "WORKDIR /app/apps/web" in web_dockerfile
    assert 'CMD ["node", "apps/web/server.js"]' in web_dockerfile


def test_docker_build_context_excludes_generated_artifacts() -> None:
    dockerignore_path = Path(__file__).parents[3] / ".dockerignore"

    assert dockerignore_path.exists()
    ignored = dockerignore_path.read_text().splitlines()
    assert "**/.next" in ignored
    assert "**/node_modules" in ignored
    assert "**/.venv" in ignored


def test_compose_applies_migrations_before_starting_api() -> None:
    root = Path(__file__).parents[3]
    compose = yaml.safe_load(
        (root / "infra" / "docker" / "compose.yml").read_text()
    )
    api_dockerfile = (root / "infra" / "docker" / "api.Dockerfile").read_text()

    assert "COPY --chown=appuser:appuser apps/api/migrations migrations" in api_dockerfile
    assert "COPY --chown=appuser:appuser apps/api/alembic.ini alembic.ini" in api_dockerfile
    assert compose["services"]["migrate"]["command"] == [
        "/app/.venv/bin/alembic",
        "-c",
        "/app/alembic.ini",
        "upgrade",
        "head",
    ]
    assert compose["services"]["api"]["depends_on"]["migrate"]["condition"] == (
        "service_completed_successfully"
    )


def test_api_worker_and_migrator_reuse_one_application_image() -> None:
    compose_path = Path(__file__).parents[3] / "infra" / "docker" / "compose.yml"
    services = yaml.safe_load(compose_path.read_text())["services"]

    assert services["api"]["image"] == "operations-ai-platform-api:${IMAGE_TAG:-local}"
    assert services["worker"]["image"] == services["api"]["image"]
    assert services["migrate"]["image"] == services["api"]["image"]
    assert "build" not in services["worker"]
    assert "build" not in services["migrate"]


def test_compose_uses_one_shot_migration_bucket_and_opt_in_demo_seed_jobs() -> None:
    compose_path = Path(__file__).parents[3] / "infra" / "docker" / "compose.yml"
    services = yaml.safe_load(compose_path.read_text())["services"]

    for service_name in ("migrate", "bucket-init", "demo-seed"):
        assert services[service_name]["restart"] == "no"
        assert services[service_name]["image"] == services["api"]["image"]
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["demo-seed"]["profiles"] == ["demo"]
    assert "alembic" not in " ".join(services["api"].get("command", []))
    assert "alembic" not in " ".join(services["worker"].get("command", []))


def test_production_images_are_multistage_and_use_production_servers() -> None:
    docker_dir = Path(__file__).parents[3] / "infra" / "docker"
    api_dockerfile = (docker_dir / "api.Dockerfile").read_text()
    web_dockerfile = (docker_dir / "web.Dockerfile").read_text()

    assert api_dockerfile.count("FROM ") >= 2
    assert web_dockerfile.count("FROM ") >= 2
    assert '"fastapi", "run"' not in api_dockerfile
    assert '"next", "dev"' not in web_dockerfile
    assert "USER appuser" in api_dockerfile
    assert "USER nextjs" in web_dockerfile


def test_fresh_install_cleanup_includes_the_explicit_demo_profile() -> None:
    root = Path(__file__).parents[3]
    script = (root / "scripts" / "verify-fresh-install.sh").read_text()

    assert 'compose --profile demo --profile e2e down --volumes --remove-orphans' in script


def test_fresh_install_preserves_failure_diagnostics_and_uses_containerized_e2e() -> None:
    root = Path(__file__).parents[3]
    script = (root / "scripts" / "verify-fresh-install.sh").read_text()
    compose = yaml.safe_load((root / "infra" / "docker" / "compose.yml").read_text())

    assert 'if [[ "$status" -ne 0 ]]' in script
    assert 'diagnostics retained at' in script
    assert 'run --rm e2e' in script
    assert compose["services"]["e2e"]["profiles"] == ["e2e"]
    assert "SESSION_SIGNING_SECRET" in compose["services"]["api"]["environment"]


def test_fresh_install_waits_for_one_shots_without_compose_wait_treating_them_as_failed() -> None:
    root = Path(__file__).parents[3]
    script = (root / "scripts" / "verify-fresh-install.sh").read_text()

    assert "compose --profile demo up --build -d" in script
    assert "compose --profile demo up -d" in script
    assert 'compose --profile demo ps -a -q "$service"' in script
    assert 'exit_code="$(docker wait "$container_id")"' in script
    assert 'for service in migrate bucket-init demo-seed; do' in script
    assert "wait_healthy api" in script
    assert "wait_healthy web" in script
    assert "compose --profile e2e build e2e" in script
    assert "up --build --wait" not in script
    assert "compose wait migrate bucket-init demo-seed" not in script


def test_web_standalone_runtime_uses_monorepo_server_path_and_static_directory() -> None:
    root = Path(__file__).parents[3]
    dockerfile = (root / "infra" / "docker" / "web.Dockerfile").read_text()

    assert 'COPY --from=builder --chown=nextjs:nextjs /app/apps/web/.next/standalone /app' in dockerfile
    assert 'COPY --from=builder --chown=nextjs:nextjs /app/apps/web/.next/static /app/apps/web/.next/static' in dockerfile
    assert 'CMD ["node", "apps/web/server.js"]' in dockerfile

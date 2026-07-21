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
    assert 'CMD ["/app/.venv/bin/fastapi"' in dockerfile
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
    assert "USER node" in web_dockerfile


def test_web_container_uses_only_root_workspace_and_direct_runtime() -> None:
    root = Path(__file__).parents[3]
    web_dockerfile = (root / "infra" / "docker" / "web.Dockerfile").read_text()

    assert not (root / "apps" / "web" / "pnpm-workspace.yaml").exists()
    assert "ENV NEXT_TELEMETRY_DISABLED=1" in web_dockerfile
    assert "WORKDIR /app/apps/web" in web_dockerfile
    assert 'CMD ["/app/apps/web/node_modules/.bin/next"' in web_dockerfile


def test_docker_build_context_excludes_generated_artifacts() -> None:
    dockerignore_path = Path(__file__).parents[3] / ".dockerignore"

    assert dockerignore_path.exists()
    ignored = dockerignore_path.read_text().splitlines()
    assert "**/.next" in ignored
    assert "**/node_modules" in ignored
    assert "**/.venv" in ignored

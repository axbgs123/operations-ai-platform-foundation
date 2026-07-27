from importlib import import_module
from importlib.util import find_spec

from fastapi.testclient import TestClient

from app.core.health import DependencyStatus, ReadinessResult, get_readiness_service


def test_health_endpoint_reports_service_is_ready() -> None:
    assert find_spec("app") is not None, "app.main must define the API entrypoint"

    module = import_module("app.main")
    client = TestClient(module.app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_does_not_depend_on_readiness_and_readiness_is_component_safe() -> None:
    module = import_module("app.main")

    class Degraded:
        def check(self) -> ReadinessResult:
            return ReadinessResult(
                status="not_ready",
                components=(
                    DependencyStatus("postgresql", "ready"),
                    DependencyStatus(
                        "redis",
                        "not_ready",
                        "DEPENDENCY_UNAVAILABLE",
                    ),
                    DependencyStatus("s3", "ready"),
                ),
            )

    module.app.dependency_overrides[get_readiness_service] = lambda: Degraded()
    try:
        client = TestClient(module.app)
        assert client.get("/health/live").json() == {"status": "alive"}
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {
            "status": "not_ready",
            "error_code": "DEPENDENCY_NOT_READY",
            "components": [
                {"name": "postgresql", "status": "ready", "error_code": None},
                {
                    "name": "redis",
                    "status": "not_ready",
                    "error_code": "DEPENDENCY_UNAVAILABLE",
                },
                {"name": "s3", "status": "ready", "error_code": None},
            ],
        }
        assert "redis://" not in response.text
    finally:
        module.app.dependency_overrides.clear()

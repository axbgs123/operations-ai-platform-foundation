from importlib import import_module
from importlib.util import find_spec

from fastapi.testclient import TestClient


def test_health_endpoint_reports_service_is_ready() -> None:
    assert find_spec("app") is not None, "app.main must define the API entrypoint"

    module = import_module("app.main")
    client = TestClient(module.app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

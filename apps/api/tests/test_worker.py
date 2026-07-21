from importlib import import_module
from importlib.util import find_spec


def test_worker_uses_configured_redis_broker(monkeypatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://queue.example:6379/3")
    assert find_spec("app.worker") is not None, "app.worker must define the worker"

    module = import_module("app.worker")

    assert module.celery_app.main == "operations_ai"
    assert module.celery_app.conf.broker_url == "redis://queue.example:6379/3"
    assert module.celery_app.conf.result_backend == "redis://queue.example:6379/3"

import os

from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "operations_ai",
    broker=redis_url,
    backend=redis_url,
)
celery_app.conf.imports = (
    "app.modules.imports.screenshot",
    "app.modules.analysis.tasks",
    "app.modules.style_facts.fact_tasks",
    "app.modules.generation.tasks",
)
celery_app.conf.beat_schedule = {
    "recover-pending-analysis-runs": {
        "task": "analysis.recover_pending",
        "schedule": 30.0,
    }
}

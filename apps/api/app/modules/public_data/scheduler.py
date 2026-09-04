from __future__ import annotations

from threading import Event, Thread

from app.modules.public_data.service import run_due_collection_jobs


class PublicDataScheduler:
    """Small in-process scheduler for the single-API deployment."""

    def __init__(self, *, interval_seconds: int) -> None:
        self._interval_seconds = max(interval_seconds, 10)
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = Thread(
            target=self._run,
            name="public-data-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                run_due_collection_jobs()
            except Exception:
                # A later tick retries database/provider outages; request handling
                # must not be affected by scheduler availability.
                continue

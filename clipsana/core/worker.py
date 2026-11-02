"""Background job runner for the API process: separate GPU and CPU slots (default 1 + 1, CLAUDE.md §3)."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Literal

log = logging.getLogger(__name__)
Slot = Literal["gpu", "cpu"]


class Worker:
    def __init__(self, gpu_slots: int = 1, cpu_slots: int = 1) -> None:
        self._slots: dict[Slot, int] = {"gpu": gpu_slots, "cpu": cpu_slots}
        self._queues: dict[Slot, queue.Queue[str | None]] = {"gpu": queue.Queue(), "cpu": queue.Queue()}
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for slot, count in self._slots.items():
            for i in range(count):
                t = threading.Thread(target=self._loop, args=(slot,), name=f"clipsana-{slot}-{i}", daemon=True)
                t.start()
                self._threads.append(t)

    def submit(self, job_id: str, slot: Slot) -> None:
        self._queues[slot].put(job_id)

    def stop(self, timeout: float = 10.0) -> None:
        from clipsana.core import service
        service.cancel_all_running()  # kill ffmpeg so no half-written output survives a shutdown
        for slot, q in self._queues.items():
            for _ in range(self._slots[slot]):
                q.put(None)
        for t in self._threads:
            t.join(timeout)

    def _loop(self, slot: Slot) -> None:
        from clipsana.core import service
        q = self._queues[slot]
        while (job_id := q.get()) is not None:
            try:
                service.run_job(job_id)
            except Exception:
                # A crash in one job must not take the slot down; the job is marked failed by run_job's guard.
                log.exception("job %s crashed", job_id)

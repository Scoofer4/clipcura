"""Background job runner for the API process: separate GPU and CPU slots (default 1 + 1, CLAUDE.md §3)."""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Literal

log = logging.getLogger(__name__)
Slot = Literal["gpu", "cpu"]
SLOTS: tuple[Slot, ...] = ("gpu", "cpu")
# How often an idle slot looks up from its queue to notice a smaller slot count or a shutdown.
_IDLE_CHECK_S = 0.25


class Worker:
    def __init__(self, gpu_slots: int = 1, cpu_slots: int = 1) -> None:
        self._target: dict[Slot, int] = {"gpu": gpu_slots, "cpu": cpu_slots}
        self._alive: dict[Slot, int] = {"gpu": 0, "cpu": 0}
        self._queues: dict[Slot, queue.Queue[str]] = {"gpu": queue.Queue(), "cpu": queue.Queue()}
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._paused = threading.Event()
        self._seq = 0

    def start(self) -> None:
        for slot in SLOTS:
            self._fill(slot)

    def resize(self, gpu: int, cpu: int) -> None:
        """Apply a new slot count now: extra slots start at once, surplus slots end after their current job
        (a running conversion is never interrupted by a settings change)."""
        with self._lock:
            self._target = {"gpu": gpu, "cpu": cpu}
        for slot in SLOTS:
            self._fill(slot)

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def pause(self) -> None:
        """Start no new jobs; running conversions finish (tray menu, #9). Not kept across restarts."""
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()

    def submit(self, job_id: str, slot: Slot) -> None:
        self._queues[slot].put(job_id)

    def stop(self, timeout: float = 10.0) -> None:
        from clipsana.core import service
        self._stopping.set()
        service.cancel_all_running()  # kill ffmpeg so no half-written output survives a shutdown
        for t in self._threads:
            t.join(timeout)

    def _fill(self, slot: Slot) -> None:
        with self._lock:
            while not self._stopping.is_set() and self._alive[slot] < self._target[slot]:
                self._alive[slot] += 1
                self._seq += 1
                t = threading.Thread(target=self._loop, args=(slot,), name=f"clipsana-{slot}-{self._seq}",
                                     daemon=True)
                self._threads.append(t)
                t.start()

    def _retire(self, slot: Slot) -> bool:
        with self._lock:
            if self._stopping.is_set() or self._alive[slot] > self._target[slot]:
                self._alive[slot] -= 1
                return True
            return False

    def _loop(self, slot: Slot) -> None:
        from clipsana.core import service
        q = self._queues[slot]
        while not self._retire(slot):
            if self._paused.is_set():
                time.sleep(_IDLE_CHECK_S)
                continue
            try:
                job_id = q.get(timeout=_IDLE_CHECK_S)
            except queue.Empty:
                continue
            if self._stopping.is_set():
                break  # picked up during shutdown: the job stays queued and the next start resumes it
            try:
                service.run_job(job_id)
            except Exception:
                # A crash in one job must not take the slot down; the job is marked failed by run_job's guard.
                log.exception("job %s crashed", job_id)

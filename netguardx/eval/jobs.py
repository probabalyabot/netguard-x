"""Evaluation runs as background jobs, so a long run does not hold one HTTP request open.

One job runs at a time (an evaluation is CPU-bound; two would only slow each other down and skew
the timings being measured). Finished jobs are kept for a while so their result can be fetched.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Optional

KEEP_FINISHED = 5


class Cancelled(Exception):
    """Raised inside a running evaluation when its job is cancelled."""


class Busy(Exception):
    """Another evaluation is already running."""


class _Job:
    def __init__(self, total: int):
        self.id = uuid.uuid4().hex[:12]
        self.status = "running"  # running | done | failed | cancelled
        self.done = 0
        self.total = total
        self.started = time.time()
        self.finished: Optional[float] = None
        self.result: Optional[dict[str, Any]] = None
        self.error: Optional[str] = None
        self.cancel = threading.Event()

    def view(self, with_result: bool = True) -> dict[str, Any]:
        out = {"id": self.id, "status": self.status, "done": self.done, "total": self.total,
               "elapsed_s": round((self.finished or time.time()) - self.started, 1)}
        if self.error:
            out["error"] = self.error
        if with_result and self.result is not None:
            out["result"] = self.result
        return out


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def start(self, total: int, work: Callable[[Callable[[int, int], None]], dict[str, Any]]) -> dict[str, Any]:
        """Run ``work(progress)`` in a thread; ``progress(done, total)`` is called as it goes."""
        with self._lock:
            if any(j.status == "running" for j in self._jobs.values()):
                raise Busy("an evaluation is already running; wait for it or cancel it")
            job = _Job(total)
            self._jobs[job.id] = job
            finished = sorted((j for j in self._jobs.values() if j.status != "running"), key=lambda j: j.started)
            for old in finished[:-KEEP_FINISHED]:
                del self._jobs[old.id]

        def progress(done: int, total: int) -> None:
            if job.cancel.is_set():
                raise Cancelled()
            job.done, job.total = done, total

        def run() -> None:
            try:
                job.result = work(progress)
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
            except Exception as exc:  # report any failure to the client instead of losing it
                job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            finally:
                job.finished = time.time()

        threading.Thread(target=run, name=f"eval-{job.id}", daemon=True).start()
        return job.view(with_result=False)

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        job = self._jobs.get(job_id)
        return job.view() if job else None

    def cancel(self, job_id: str) -> Optional[dict[str, Any]]:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        job.cancel.set()
        return job.view(with_result=False)

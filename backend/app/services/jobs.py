"""In-memory background jobs for slow operations (LLM calls).

Recommendation and photo classification can take 10-60s with a small
local model — longer than some mobile HTTP stacks will happily hold a
connection open. Clients submit a job and poll GET /api/jobs/{id}
instead. Single-user local app: an in-process store is enough.
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

_TTL_SECONDS = 3600.0  # finished jobs are forgotten after an hour


class JobStore:
    def __init__(self, max_workers: int = 2):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def submit(self, fn) -> str:
        """Run fn in the background; return the job id immediately."""
        return self._submit(lambda report: fn())

    def submit_reporting(self, fn) -> str:
        """Like submit, but fn receives a report(progress: dict) callable
        it may call from inside the worker to publish live progress
        (exposed as JobStatus.progress by GET /api/jobs/{id}). Jobs that
        never report simply show progress: null — backward compatible.
        """
        return self._submit(fn)

    def _submit(self, fn) -> str:
        self._sweep()
        job_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._jobs[job_id] = {
                "status": "queued",
                "created": time.monotonic(),
                "result": None,
                "error": None,
                "progress": None,
            }
        # The reporter is created up front (not inside submit's caller) so
        # the worker can never race the id assignment in the request thread.
        self._executor.submit(self._run, job_id, lambda: fn(self._reporter(job_id)))
        return job_id

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return {"job_id": job_id, **job} if job else None

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False)

    def _reporter(self, job_id: str):
        """A callable the job's fn can use to publish live progress."""

        def report(progress: dict) -> None:
            self._transition(job_id, progress=progress)

        return report

    def _run(self, job_id: str, fn) -> None:
        self._transition(job_id, status="running")
        try:
            result = fn()
            self._transition(job_id, status="done", result=result)
        except Exception as exc:  # surfaced to the client as a failed job
            self._transition(job_id, status="failed", error=str(exc) or type(exc).__name__)

    def _transition(self, job_id: str, **fields) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)

    def _sweep(self) -> None:
        """Forget finished jobs older than the TTL."""
        now = time.monotonic()
        with self._lock:
            stale = [
                job_id for job_id, job in self._jobs.items()
                if job["status"] in ("done", "failed") and now - job["created"] > _TTL_SECONDS
            ]
            for job_id in stale:
                del self._jobs[job_id]

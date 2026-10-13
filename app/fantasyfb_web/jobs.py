"""
In-memory background job queue for simulation runs.

A run takes from tens of seconds to several minutes, so the web request only
queues it and the browser polls for status. This is deliberately the simplest
thing that works on a single server process: jobs live in a dict and are lost
on restart. Swap in RQ/Celery plus a results store before running more than
one worker process.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .pipeline import RunOptions

log = logging.getLogger(__name__)

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass
class Job:
    id: str
    opts: RunOptions
    status: str = QUEUED
    stage: str = "Waiting for a free worker"
    stages: List[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    started: Optional[float] = None
    finished: Optional[float] = None
    html: Optional[str] = None
    error: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.status in (QUEUED, RUNNING)


class JobManager:
    """
    Runs ``runner(opts, progress)`` on a small thread pool and tracks the result.

    Job IDs are random UUIDs, so a run's URL works as an unguessable share
    link without any accounts.
    """

    def __init__(
        self,
        runner: Callable[[RunOptions, Callable[[str], None]], str],
        max_workers: int = 1,
        ttl_seconds: float = 6 * 3600,
        max_jobs: int = 200,
    ):
        # One worker by default: a run is CPU-heavy and League construction
        # touches shared on-disk caches (nflreadpy, Sleeper players).
        self._runner = runner
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fantasyfb-run")
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max_jobs = max_jobs

    def submit(self, opts: RunOptions) -> Job:
        """Queue a run, or return the identical run that's already queued or running."""
        with self._lock:
            self._prune()
            for job in self._jobs.values():
                if job.active and job.opts == opts:
                    return job
            if sum(job.active for job in self._jobs.values()) >= self._max_jobs:
                raise QueueFull()
            job = Job(id=uuid.uuid4().hex, opts=opts)
            self._jobs[job.id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def queue_position(self, job: Job) -> int:
        """How many runs are ahead of ``job`` (0 once it's running)."""
        if job.status != QUEUED:
            return 0
        with self._lock:
            return sum(
                1 for other in self._jobs.values()
                if other.active and other.created < job.created
            )

    def _run(self, job: Job) -> None:
        def progress(stage: str) -> None:
            job.stage = stage
            job.stages.append(stage)

        job.status, job.started = RUNNING, time.time()
        try:
            job.html = self._runner(job.opts, progress)
            job.status = DONE
        except Exception as exc:  # surfaced to the user, so keep it short
            log.exception("Run %s failed", job.id)
            job.error = _user_message(exc)
            job.status = FAILED
        finally:
            job.finished = time.time()

    def _prune(self) -> None:
        """Drop finished jobs older than the TTL. Caller holds the lock."""
        cutoff = time.time() - self._ttl
        for job_id in [
            j.id for j in self._jobs.values()
            if not j.active and (j.finished or j.created) < cutoff
        ]:
            del self._jobs[job_id]


class QueueFull(RuntimeError):
    """Too many runs are already waiting."""


def _user_message(exc: Exception) -> str:
    # ValueErrors from League are written for users (e.g. "No Sleeper team
    # found matching ..."); anything else is an internal failure.
    if isinstance(exc, ValueError):
        return str(exc)
    return f"The simulation failed ({type(exc).__name__}). Try again in a few minutes."

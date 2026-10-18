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
import multiprocessing
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from fantasyfb.data.yahoo_auth import YahooAuthError, YahooTokenAuth

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
    # Set for runs on private data (Yahoo): only the browser session that
    # started it may see the result, and ``auth`` holds that user's tokens
    # for the run's duration. ``repr=False`` keeps tokens out of logs.
    owner: Optional[str] = None
    auth: Optional[object] = field(default=None, repr=False)
    # Who asked (session ID or IP address), for the one-active-run-per-client limit.
    client_key: Optional[str] = field(default=None, repr=False)

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
        max_jobs: int = 10,
        isolate: bool = False,
        timeout_seconds: float = 20 * 60,
    ):
        """
        Args:
            max_jobs: Most queued-or-running runs allowed at once. Kept small
                because each run takes minutes, so a long queue is a long wait.
            isolate: Run each job in a child process so a timeout can really
                stop it and a crash or out-of-memory kill only fails that run.
                ``runner`` must then be importable by name (module level), not
                a closure. Off by default so tests can inject simple stubs.
            timeout_seconds: With ``isolate``, kill a run after this long.
        """
        # One worker by default: a run is CPU-heavy and League construction
        # touches shared on-disk caches (nflreadpy, Sleeper players).
        self._runner = runner
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fantasyfb-run")
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds
        self._max_jobs = max_jobs
        self._isolate = isolate
        self._timeout = timeout_seconds

    def submit(
        self,
        opts: RunOptions,
        owner: Optional[str] = None,
        auth: Optional[object] = None,
        client_key: Optional[str] = None,
    ) -> Job:
        """
        Queue a run, or return the identical run that's already queued or running.

        Runs with an ``owner`` are never shared: two users asking for the same
        thing each get their own job, because the result is private.

        Raises:
            QueueFull: too many runs are waiting
            TooManyRuns: ``client_key`` already has a different run in progress
        """
        with self._lock:
            self._prune()
            if owner is None:
                for job in self._jobs.values():
                    if job.active and job.owner is None and job.opts == opts:
                        return job
            if client_key is not None and any(
                job.active and job.client_key == client_key for job in self._jobs.values()
            ):
                raise TooManyRuns()
            if sum(job.active for job in self._jobs.values()) >= self._max_jobs:
                raise QueueFull()
            job = Job(id=uuid.uuid4().hex, opts=opts, owner=owner, auth=auth, client_key=client_key)
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
            if self._isolate:
                self._run_in_child(job, progress)
            else:
                if job.auth is not None:
                    job.html = self._runner(job.opts, progress, auth=job.auth)
                else:
                    job.html = self._runner(job.opts, progress)
                job.status = DONE
        except Exception as exc:  # surfaced to the user, so keep it short
            log.exception("Run %s failed", job.id)
            job.error = _user_message(exc)
            job.status = FAILED
        finally:
            job.finished = time.time()
            job.auth = None  # the session keeps the tokens; the job doesn't need them anymore

    def _run_in_child(self, job: Job, progress: Callable[[str], None]) -> None:
        """
        Run the job in a fresh (spawned) child process and relay its messages.

        A thread can't be killed, so a stuck simulation would hold the only
        worker forever; a process can be. Spawn rather than fork, because
        forking a process with live threads and numerical libraries is unsafe.
        """
        ctx = multiprocessing.get_context("spawn")
        receiver, sender = ctx.Pipe(duplex=False)
        auth_state = job.auth.export_state() if job.auth is not None else None
        proc = ctx.Process(
            target=_child_main, args=(self._runner, job.opts, auth_state, sender), daemon=True
        )
        proc.start()
        sender.close()  # only the child holds the write end, so its death reads as EOF
        deadline = time.time() + self._timeout
        outcome = None  # ("done", html) or ("error", message)
        timed_out = False
        try:
            while True:
                if receiver.poll(0.25):
                    try:
                        kind, payload = receiver.recv()
                    except EOFError:
                        break  # the child exited and everything it sent has been read
                    if kind == "progress":
                        progress(payload)
                    elif kind == "auth" and job.auth is not None:
                        job.auth.adopt(payload)
                    else:
                        outcome = (kind, payload)
                elif time.time() > deadline:
                    timed_out = True
                    break
        finally:
            _stop(proc)
            receiver.close()

        if timed_out:
            job.error = f"This run took longer than {int(self._timeout // 60)} minutes and was stopped. Try fewer simulations."
            job.status = FAILED
        elif outcome and outcome[0] == "done":
            job.html = outcome[1]
            job.status = DONE
        elif outcome:
            job.error = outcome[1]
            job.status = FAILED
        else:
            log.error("Run %s: child exited without a result (exit code %s)", job.id, proc.exitcode)
            job.error = "The simulation crashed, most likely by running out of memory. Try fewer simulations."
            job.status = FAILED

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


class TooManyRuns(RuntimeError):
    """This client already has a run in progress."""


def _child_main(runner, opts, auth_state, conn) -> None:
    """Entry point of a run's child process. Reports back over ``conn``."""
    auth = YahooTokenAuth.from_state(auth_state) if auth_state is not None else None
    try:
        try:
            progress = lambda stage: conn.send(("progress", stage))  # noqa: E731
            html = runner(opts, progress, auth=auth) if auth is not None else runner(opts, progress)
            conn.send(("done", html))
        except Exception as exc:
            log.exception("Run failed")
            conn.send(("error", _user_message(exc)))
        if auth is not None:
            conn.send(("auth", auth.export_state()))  # the run may have refreshed the tokens
    finally:
        conn.close()


def _stop(proc) -> None:
    """Make sure a child process is gone."""
    if proc.is_alive():
        proc.terminate()
        proc.join(5)
    if proc.is_alive():
        proc.kill()
    proc.join(5)


def _user_message(exc: Exception) -> str:
    # ValueErrors from League are written for users (e.g. "No Sleeper team
    # found matching ..."); anything else is an internal failure.
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, YahooAuthError):
        return "Yahoo no longer accepts your sign-in. Sign in with Yahoo again and re-run."
    return f"The simulation failed ({type(exc).__name__}). Try again in a few minutes."

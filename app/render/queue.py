"""Export queue: runs exports one at a time, in submission order, as tracked jobs.

Job records are kept in memory and mirrored to a JSON file, so the history survives a
restart. Progress and the ETA come from export()'s progress callback, which is fed by
ffmpeg's `-progress pipe:1` output. Cancelling stops the ffmpeg processes; export() then
deletes the partial output.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.overlays.registry import OverlayRegistry, default_registry
from app.telemetry.cache import DEFAULT_CACHE_ROOT

from .export import ExportCancelled, ExportError, export
from .naming import DEFAULT_EXPORTS_DIR

log = logging.getLogger(__name__)

DEFAULT_JOBS_PATH = Path(__file__).resolve().parents[2] / "data" / "jobs.json"
TERMINAL_STATES: tuple[str, ...] = ("completed", "failed", "cancelled")
PERSIST_INTERVAL = 0.5  # seconds between progress writes to the jobs file
INTERRUPTED = "interrupted: the app stopped before this export finished"
CANCELLED = "cancelled by user"


@dataclass
class Job:
    """One export as seen by callers. `progress` is a percentage from 0 to 100."""

    id: str
    clip: str
    config: dict[str, Any]
    preset: str
    start: float | None
    end: float | None
    mount: str
    state: str = "queued"
    progress: float = 0.0
    eta_s: float | None = None
    output: str | None = None
    reason: str | None = None
    submitted_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None


@dataclass
class _Runtime:
    """Per-job state the worker and the callers share, which is not part of the record."""

    cancel: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    processes: list[subprocess.Popen] = field(default_factory=list)
    started: float = 0.0


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ExportQueue:
    """Runs submitted exports on one worker thread, first in, first out."""

    def __init__(
        self,
        *,
        registry: OverlayRegistry = default_registry,
        export_fn: Callable[..., Path] = export,
        jobs_path: Path = DEFAULT_JOBS_PATH,
        exports_dir: Path = DEFAULT_EXPORTS_DIR,
        cache_root: Path = DEFAULT_CACHE_ROOT,
    ) -> None:
        self._registry = registry
        self._cache_root = Path(cache_root)
        self._export = export_fn
        self._jobs_path = Path(jobs_path)
        self._exports_dir = Path(exports_dir)
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._runtime: dict[str, _Runtime] = {}
        self._pending: queue.Queue[str | None] = queue.Queue()
        self._last_write = 0.0
        self._load()
        self._worker = threading.Thread(target=self._work, name="export-worker", daemon=True)
        self._worker.start()

    # Public API

    def submit(
        self,
        clip: str | Path,
        config: Mapping[str, Any],
        *,
        preset: str = "original",
        start: float | None = None,
        end: float | None = None,
        mount: str = "bike",
    ) -> str:
        """Queue an export and return its job id. Validation errors show up as a failed job."""
        job = Job(
            id=uuid.uuid4().hex,
            clip=str(clip),
            config=copy.deepcopy(dict(config)),
            preset=preset,
            start=start,
            end=end,
            mount=mount,
            submitted_at=_now(),
        )
        with self._lock:
            self._jobs[job.id] = job
            self._runtime[job.id] = _Runtime()
            self._save(force=True)
        self._pending.put(job.id)
        return job.id

    def get(self, job_id: str) -> Job:
        """Return a copy of the job record. Raises KeyError for an unknown id."""
        with self._lock:
            return copy.deepcopy(self._jobs[job_id])

    def jobs(self) -> list[Job]:
        """Return copies of all job records, in submission order."""
        with self._lock:
            return [copy.deepcopy(j) for j in self._jobs.values()]

    def wait(self, job_id: str, timeout: float | None = None) -> Job:
        """Block until the job reaches a terminal state or `timeout` seconds pass, then return it."""
        runtime = self._runtime[job_id]
        runtime.done.wait(timeout)
        return self.get(job_id)

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued or running job. Returns False if the job has already finished.

        A queued job never starts. A running job's ffmpeg processes are killed, and the job
        becomes cancelled once the export has cleaned up.
        """
        with self._lock:
            job = self._jobs[job_id]
            runtime = self._runtime[job_id]
            if job.state == "queued":
                job.state = "cancelled"
                job.reason = CANCELLED
                job.finished_at = _now()
                runtime.cancel.set()
                runtime.done.set()
                self._save(force=True)
                return True
            if job.state == "running":
                runtime.cancel.set()
                for proc in runtime.processes:
                    if proc.poll() is None:
                        proc.kill()
                return True
            return False

    def close(self) -> None:
        """Stop the worker after the jobs already queued have run."""
        self._pending.put(None)

    # Worker

    def _work(self) -> None:
        while True:
            job_id = self._pending.get()
            if job_id is None:
                return
            with self._lock:
                job = self._jobs[job_id]
                if job.state != "queued":
                    continue  # cancelled while it waited
                job.state = "running"
                job.started_at = _now()
                self._runtime[job_id].started = time.monotonic()
                self._save(force=True)
            self._run(job)

    def _run(self, job: Job) -> None:
        runtime = self._runtime[job.id]
        try:
            output = self._export(
                job.clip,
                job.config,
                preset=job.preset,
                start=job.start,
                end=job.end,
                mount=job.mount,
                registry=self._registry,
                exports_dir=self._exports_dir,
                progress=lambda fraction: self._progress(job.id, fraction),
                should_cancel=runtime.cancel.is_set,
                on_process=lambda proc: self._track(job.id, proc),
                cache_root=self._cache_root,
            )
        except Exception as exc:  # every failure becomes a job state, none escapes the worker
            self._finish(job.id, error=exc)
        else:
            self._finish(job.id, output=output)

    def _track(self, job_id: str, proc: subprocess.Popen) -> None:
        with self._lock:
            runtime = self._runtime[job_id]
            runtime.processes.append(proc)
            if runtime.cancel.is_set():
                proc.kill()  # cancel arrived before this process started

    def _progress(self, job_id: str, fraction: float) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.state != "running":
                return
            percent = min(max(fraction * 100.0, job.progress), 100.0)  # never goes backwards
            elapsed = time.monotonic() - self._runtime[job_id].started
            job.progress = percent
            job.eta_s = round(elapsed * (100.0 - percent) / percent, 1) if percent > 0 else None
            self._save()

    def _finish(self, job_id: str, output: Path | None = None, error: Exception | None = None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            runtime = self._runtime[job_id]
            if runtime.cancel.is_set() or isinstance(error, ExportCancelled):
                if output is not None:
                    _discard(output)
                job.state = "cancelled"
                job.reason = CANCELLED
            elif error is None:
                job.state = "completed"
                job.progress = 100.0
                job.eta_s = 0.0
                job.output = str(output)
            else:
                job.state = "failed"
                job.reason = _reason(error)
                job.eta_s = None
            job.finished_at = _now()
            self._save(force=True)
            runtime.done.set()

    # Persistence

    def _load(self) -> None:
        if not self._jobs_path.exists():
            return
        try:
            records = json.loads(self._jobs_path.read_text(encoding="utf-8"))
            loaded = [Job(**record) for record in records]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("ignoring unreadable job history %s: %s", self._jobs_path, exc)
            return
        for job in loaded:
            if job.state not in TERMINAL_STATES:
                job.state = "failed"
                job.reason = INTERRUPTED
                job.finished_at = job.finished_at or _now()
            self._jobs[job.id] = job
            runtime = _Runtime()
            runtime.done.set()  # a restored job is already finished, so waiting on it returns at once
            self._runtime[job.id] = runtime

    def _save(self, force: bool = False) -> None:
        """Mirror the job records to the jobs file. Progress writes are throttled; the caller holds the lock."""
        now = time.monotonic()
        if not force and now - self._last_write < PERSIST_INTERVAL:
            return
        self._last_write = now
        records = [asdict(job) for job in self._jobs.values()]
        tmp = self._jobs_path.with_name(self._jobs_path.name + ".tmp")
        try:
            self._jobs_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(records, indent=2), encoding="utf-8")
            os.replace(tmp, self._jobs_path)
        except OSError as exc:
            log.warning("could not write job history %s: %s", self._jobs_path, exc)


def _reason(error: Exception) -> str:
    if isinstance(error, ExportError):
        return str(error)
    log.error("export failed unexpectedly: %s", error, exc_info=error)
    return f"unexpected error: {error or type(error).__name__}"


def _discard(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass

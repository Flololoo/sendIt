"""Background work on imported clips: telemetry, cover thumbnail and proxy generation.

Every job reads its clip, moves the clip's status pending -> running -> done (or failed), and
never raises into the pool. Jobs run on a small thread pool so the UI is never blocked by them.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path

from app.telemetry import get_telemetry

from . import media
from .library import DONE, FAILED, PENDING, RUNNING, Clip, Library
from .paths import WorkspacePaths

log = logging.getLogger(__name__)

WORKERS = 2
THUMBNAIL_NAME = "thumb.jpg"
PROXY_NAME = "proxy.mp4"


class Jobs:
    def __init__(self, library: Library, paths: WorkspacePaths, *, workers: int = WORKERS) -> None:
        self._library = library
        self._paths = paths
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="workspace-job")
        self._lock = threading.Lock()
        self._futures: set[Future] = set()
        self._cancelled: set[str] = set()  # proxy jobs asked to stop (clip removed or replaced by an LRF)
        self._closing = False

    # Scheduling

    def start(self, clip: Clip) -> None:
        """Queue the jobs of a clip whose status is still pending."""
        if clip.telemetry_status == PENDING:
            self._submit(self.run_telemetry, clip.id)
        if clip.thumbnail_status == PENDING:
            self._submit(self.run_thumbnail, clip.id)
        if clip.proxy_status == PENDING:
            self._submit(self.run_proxy, clip.id)

    def resume(self) -> None:
        """Requeue jobs an earlier run left pending or running, such as after the app stopped mid-job."""
        for clip in self._library.all():
            updates = {
                column: PENDING
                for column, status in (
                    ("telemetry_status", clip.telemetry_status),
                    ("thumbnail_status", clip.thumbnail_status),
                    ("proxy_status", clip.proxy_status),
                )
                if status == RUNNING
            }
            if updates:
                self._library.update(clip.id, **updates)
        for clip in self._library.all():
            self.start(clip)

    def cancel_proxy(self, clip_id: str) -> None:
        with self._lock:
            self._cancelled.add(clip_id)

    def wait_idle(self, timeout: float | None = None) -> None:
        """Block until every queued job has finished. Used by tests and at shutdown."""
        while True:
            with self._lock:
                pending = list(self._futures)
            if not pending:
                return
            _, not_done = wait(pending, timeout=timeout)
            if not_done:
                return  # timed out

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _submit(self, fn, clip_id: str) -> None:
        future = self._pool.submit(fn, clip_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._finished)

    def _finished(self, future: Future) -> None:
        with self._lock:
            self._futures.discard(future)
        if not future.cancelled() and future.exception() is not None:
            log.error("background job crashed: %s", future.exception(), exc_info=future.exception())

    # Jobs

    def run_telemetry(self, clip_id: str) -> None:
        clip = self._library.get(clip_id)
        if clip is None:
            return
        self._library.update(clip_id, telemetry_status=RUNNING)
        try:
            telemetry = get_telemetry(clip.source_path, cache_root=self._paths.cache_dir)
        except Exception as exc:  # recorded on the clip, never raised into the pool
            log.warning("telemetry failed for %s: %s", clip.name, exc)
            self._library.update(clip_id, telemetry_status=FAILED, error=f"telemetry: {exc}")
            return
        self._library.update(clip_id, meta=telemetry.meta, telemetry_status=DONE)

    def run_thumbnail(self, clip_id: str) -> None:
        clip = self._library.get(clip_id)
        if clip is None:
            return
        self._library.update(clip_id, thumbnail_status=RUNNING)
        out = self._clip_dir(clip_id) / THUMBNAIL_NAME
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            media.make_thumbnail(Path(clip.source_path), out, clip.meta)
        except Exception as exc:
            log.warning("thumbnail failed for %s: %s", clip.name, exc)
            self._library.update(clip_id, thumbnail_status=FAILED, error=f"thumbnail: {exc}")
            return
        self._library.update(clip_id, thumbnail_status=DONE)

    def run_proxy(self, clip_id: str) -> None:
        clip = self._library.get(clip_id)
        with self._lock:
            cancelled = clip_id in self._cancelled
            self._cancelled.discard(clip_id)
        if clip is None or cancelled:
            return
        # Claim the job only if it is still pending; an LRF attached in the meantime wins.
        if not self._library.update(
            clip_id, only_if={"proxy_status": PENDING}, proxy_status=RUNNING, proxy_progress=0.0
        ):
            return

        out = self._clip_dir(clip_id) / PROXY_NAME

        def progress(fraction: float) -> None:
            self._library.update(clip_id, proxy_progress=round(fraction * 100.0, 1))

        def should_cancel() -> bool:
            with self._lock:
                return self._closing or clip_id in self._cancelled

        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            finished = media.make_proxy(
                Path(clip.source_path), out, clip.meta, progress=progress, should_cancel=should_cancel
            )
        except Exception as exc:
            log.warning("proxy failed for %s: %s", clip.name, exc)
            self._library.update(
                clip_id, only_if={"proxy_status": RUNNING}, proxy_status=FAILED, error=f"proxy: {exc}"
            )
            return
        with self._lock:
            self._cancelled.discard(clip_id)
        if not finished:
            return  # cancelled; the clip is being removed or has an LRF, so there is nothing to record
        attached = self._library.update(
            clip_id,
            only_if={"proxy_status": RUNNING},
            proxy_path=str(out),
            proxy_status=DONE,
            proxy_progress=100.0,
            error=None,
        )
        if not attached:
            out.unlink(missing_ok=True)  # the clip went away or got an LRF while this was encoding

    def _clip_dir(self, clip_id: str) -> Path:
        return self._paths.clip_cache_dir / clip_id

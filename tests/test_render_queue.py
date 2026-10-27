import errno
import importlib
import json
import threading
import time
from pathlib import Path

import pytest
from overlay_fixtures import TimestampOverlay, make_clip

from app.overlays.registry import OverlayRegistry
from app.render.queue import INTERRUPTED, ExportQueue
from app.telemetry import ffmpeg_io

export_mod = importlib.import_module("app.render.export")

CLIP = Path(__file__).resolve().parents[1] / "videos" / "DJI_20261026155823_0051_D.MP4"
requires_clip = pytest.mark.skipif(not CLIP.exists(), reason="needs clip 0051 in videos/")
CONFIG = {"timestamp": {}}


def _registry() -> OverlayRegistry:
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    return reg


class FakeExport:
    """Stands in for export(). Reports each fraction, then waits for the test to release it."""

    def __init__(self, out_dir: Path, fractions=(0.5,)):
        self.out_dir = out_dir
        self.fractions = fractions
        self.started: list[str] = []
        self.ready = threading.Semaphore(0)
        self.go = threading.Semaphore(0)

    def __call__(self, clip, config, *, progress=None, **kwargs):
        self.started.append(str(clip))
        for fraction in self.fractions:
            progress(fraction)
            self.ready.release()
            self.go.acquire()
        out = self.out_dir / f"{Path(str(clip)).stem}.mp4"
        out.write_bytes(b"fake")
        return out


@pytest.fixture
def queues(tmp_path):
    """Build queues that write under tmp_path, and stop their workers after the test."""
    created: list[ExportQueue] = []

    def make(export_fn=None, registry=None, jobs_path=None):
        q = ExportQueue(
            registry=registry or _registry(),
            export_fn=export_fn or FakeExport(tmp_path),
            jobs_path=jobs_path or tmp_path / "data" / "jobs.json",
            exports_dir=tmp_path / "exports",
        )
        created.append(q)
        return q

    yield make
    for q in created:
        q.close()


def _exports(tmp_path: Path) -> list[Path]:
    return list((tmp_path / "exports").glob("*")) if (tmp_path / "exports").exists() else []


def test_second_job_queues_behind_first(tmp_path, queues):
    fake = FakeExport(tmp_path)
    q = queues(fake)
    first = q.submit("a.MP4", CONFIG)
    second = q.submit("b.MP4", CONFIG)

    assert fake.ready.acquire(timeout=10)
    assert q.get(first).state == "running"
    assert q.get(second).state == "queued"
    assert fake.started == ["a.MP4"]

    fake.go.release()
    assert fake.ready.acquire(timeout=10)  # the second job starts only after the first finished
    assert q.get(first).state == "completed"
    assert q.get(second).state == "running"

    fake.go.release()
    assert q.wait(second, timeout=10).state == "completed"
    assert fake.started == ["a.MP4", "b.MP4"]


def test_progress_is_monotonic_and_ends_at_100(tmp_path, queues):
    fake = FakeExport(tmp_path, fractions=(0.2, 0.1, 0.6, 1.0))  # a backwards step must not show
    q = queues(fake)
    job_id = q.submit("a.MP4", CONFIG)

    samples = []
    for _ in fake.fractions:
        assert fake.ready.acquire(timeout=10)
        job = q.get(job_id)
        assert job.state == "running"
        samples.append(job.progress)
        if job.progress > 0:
            assert job.eta_s is not None
        fake.go.release()

    job = q.wait(job_id, timeout=10)
    assert job.state == "completed"
    assert job.progress == 100.0
    assert job.output == str(tmp_path / "a.mp4")
    assert samples == sorted(samples)
    assert samples == [20.0, 20.0, 60.0, 100.0]


def test_job_history_is_mirrored_and_restored(tmp_path, queues):
    fake = FakeExport(tmp_path, fractions=())
    jobs_path = tmp_path / "data" / "jobs.json"
    q = queues(fake, jobs_path=jobs_path)
    job_id = q.submit("a.MP4", CONFIG)
    assert q.wait(job_id, timeout=10).state == "completed"

    records = json.loads(jobs_path.read_text(encoding="utf-8"))
    assert records[0]["id"] == job_id
    assert records[0]["state"] == "completed"
    assert records[0]["progress"] == 100.0

    # A job still marked running when the app stopped is reported as interrupted on restart.
    records[0]["state"] = "running"
    records[0]["progress"] = 40.0
    jobs_path.write_text(json.dumps(records), encoding="utf-8")
    restarted = queues(fake, jobs_path=jobs_path)
    job = restarted.get(job_id)
    assert job.state == "failed"
    assert job.reason == INTERRUPTED


def test_job_ids_are_unique(tmp_path, queues):
    q = queues(FakeExport(tmp_path, fractions=()))
    ids = [q.submit("a.MP4", CONFIG) for _ in range(5)]
    assert len(set(ids)) == 5
    for job_id in ids:
        q.wait(job_id, timeout=10)


def test_cancel_queued_job_means_it_never_starts(tmp_path, queues):
    fake = FakeExport(tmp_path)
    q = queues(fake)
    first = q.submit("a.MP4", CONFIG)
    second = q.submit("b.MP4", CONFIG)
    assert fake.ready.acquire(timeout=10)

    assert q.cancel(second) is True
    assert q.get(second).state == "cancelled"

    fake.go.release()
    assert q.wait(first, timeout=10).state == "completed"
    third = q.submit("c.MP4", CONFIG)
    assert fake.ready.acquire(timeout=10)  # the cancelled job was skipped
    assert fake.started == ["a.MP4", "c.MP4"]
    fake.go.release()
    assert q.wait(third, timeout=10).state == "completed"


def test_cancel_finished_job_returns_false(tmp_path, queues):
    q = queues(FakeExport(tmp_path, fractions=()))
    job_id = q.submit("a.MP4", CONFIG)
    q.wait(job_id, timeout=10)
    assert q.cancel(job_id) is False


@requires_clip
def test_cancel_running_export_stops_and_removes_partial_output(tmp_path, queues):
    q = queues(registry=_registry(), export_fn=export_mod.export)
    job_id = q.submit(CLIP, CONFIG, preset="social", start=300, end=330)

    deadline = time.monotonic() + 120
    while True:
        job = q.wait(job_id, timeout=0.2)
        assert job.state in ("queued", "running"), f"export ended early: {job.reason}"
        if job.state == "running" and job.progress >= 5:
            break
        assert time.monotonic() < deadline, "export never reported progress"
    assert q.cancel(job_id) is True  # mid-render: ffmpeg is running

    job = q.wait(job_id, timeout=60)
    assert job.state == "cancelled"
    assert job.reason == "cancelled by user"
    assert _exports(tmp_path) == []


def test_missing_ffmpeg_fails_with_reason_naming_ffmpeg(tmp_path, queues, monkeypatch):
    monkeypatch.setattr(ffmpeg_io.shutil, "which", lambda name: None)
    q = queues(export_fn=export_mod.export)
    job = q.wait(q.submit("DJI_TEST_0051_D.MP4", CONFIG), timeout=30)
    assert job.state == "failed"
    assert "ffmpeg" in job.reason
    assert _exports(tmp_path) == []


def test_unreadable_source_fails_with_reason_naming_the_file(tmp_path, queues):
    q = queues(export_fn=export_mod.export)
    job = q.wait(q.submit(tmp_path / "missing_clip.MP4", CONFIG), timeout=30)
    assert job.state == "failed"
    assert "could not be read" in job.reason
    assert "missing_clip.MP4" in job.reason


def test_disk_full_fails_with_reason_and_removes_partial_output(tmp_path, queues, monkeypatch):
    monkeypatch.setattr(export_mod, "load_clip", lambda path, mount, **kwargs: make_clip(False))

    def ffmpeg_out_of_space(run, cmd, duration):
        # What pass 2 reports when the disk fills up part way through the encode.
        return False, True, "Error writing trailer: No space left on device"

    monkeypatch.setattr(export_mod, "_run_pass2", ffmpeg_out_of_space)
    q = queues(export_fn=export_mod.export)
    job = q.wait(q.submit("DJI_TEST_0051_D.MP4", CONFIG, start=0, end=1, preset="social"), timeout=60)
    assert job.state == "failed"
    assert "insufficient disk space" in job.reason
    assert _exports(tmp_path) == []


def test_enospc_oserror_is_reported_as_insufficient_disk_space(tmp_path, queues, monkeypatch):
    def write_fails(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(export_mod, "load_clip", lambda path, mount, **kwargs: make_clip(False))
    monkeypatch.setattr(export_mod, "write_overlay_layer", write_fails)
    q = queues(export_fn=export_mod.export)
    job = q.wait(q.submit("DJI_TEST_0051_D.MP4", CONFIG, start=0, end=1), timeout=60)
    assert job.state == "failed"
    assert "insufficient disk space" in job.reason
    assert _exports(tmp_path) == []

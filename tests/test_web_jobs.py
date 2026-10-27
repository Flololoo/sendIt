"""Task 2.3: background telemetry, thumbnail and proxy jobs move their statuses pending -> running -> done."""

import importlib
from pathlib import Path

from helpers import fixture_telemetry
from web_support import drain, make_clip, wait_for

jobs_mod = importlib.import_module("app.workspace.jobs")
media_mod = importlib.import_module("app.workspace.media")


def _bare_clip(ws, source):
    """A clip row with no jobs queued, so a test can run one job by hand."""
    return ws.library.insert(
        name=source.name,
        origin="reference",
        source_path=str(source),
        size=source.stat().st_size if source.exists() else 0,
        mtime=None,
        meta=fixture_telemetry().meta,
    )


def test_clip_without_lrf_gets_thumbnail_telemetry_and_a_playable_proxy(web_client, web_app, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_20261026164225_0053_D.MP4")
    web_client.post("/api/import-folder", json={"path": str(source.parent)})
    drain(web_app.state.workspace)

    clip = web_client.get("/api/clips").json()[0]
    assert clip["telemetry_status"] == "done"
    assert clip["thumbnail_status"] == "done"
    assert clip["thumbnail_url"] == f"/api/clips/{clip['id']}/thumbnail"
    assert clip["proxy_status"] == "done"
    assert clip["proxy_progress"] == 100.0
    assert clip["playable"] is True

    proxy = web_client.get(clip["proxy_url"])
    assert proxy.status_code == 200
    assert proxy.headers["content-type"] == "video/mp4"


def test_telemetry_job_runs_from_pending_through_running_to_done(web_app, tmp_path, monkeypatch):
    ws = web_app.state.workspace
    clip = _bare_clip(ws, make_clip(tmp_path / "src" / "t.MP4"))
    seen = []

    def fake_get_telemetry(path, cache_root):
        seen.append(ws.library.get(clip.id).telemetry_status)
        return fixture_telemetry()

    monkeypatch.setattr(jobs_mod, "get_telemetry", fake_get_telemetry)
    assert ws.library.get(clip.id).telemetry_status == "pending"
    ws.jobs.run_telemetry(clip.id)

    assert seen == ["running"]
    done = ws.library.get(clip.id)
    assert done.telemetry_status == "done"
    assert done.meta.model == fixture_telemetry().meta.model  # the telemetry metadata replaces the probe's


def test_thumbnail_job_runs_from_pending_through_running_to_done(web_app, tmp_path):
    ws = web_app.state.workspace
    clip = _bare_clip(ws, make_clip(tmp_path / "src" / "th.MP4"))
    assert ws.library.get(clip.id).thumbnail_status == "pending"
    ws.jobs.run_thumbnail(clip.id)

    done = ws.library.get(clip.id)
    assert done.thumbnail_status == "done"
    assert (ws.paths.clip_cache_dir / clip.id / "thumb.jpg").read_bytes()[:2] == b"\xff\xd8"  # a JPEG


def test_proxy_job_reports_progress_and_finishes_done(web_app, tmp_path, monkeypatch):
    ws = web_app.state.workspace
    clip = _bare_clip(ws, make_clip(tmp_path / "src" / "p.MP4"))
    seen = []

    def fake_make_proxy(source, out, meta, *, progress, should_cancel):
        seen.append(ws.library.get(clip.id).proxy_status)
        progress(0.5)
        seen.append(ws.library.get(clip.id).proxy_progress)
        out.write_bytes(b"proxy")
        return True

    monkeypatch.setattr(media_mod, "make_proxy", fake_make_proxy)
    ws.jobs.run_proxy(clip.id)

    assert seen == ["running", 50.0]
    done = ws.library.get(clip.id)
    assert done.proxy_status == "done"
    assert done.proxy_progress == 100.0
    assert done.proxy_path is not None and Path(done.proxy_path).read_bytes() == b"proxy"


def test_a_failed_job_records_the_reason_on_the_clip(web_app, tmp_path):
    ws = web_app.state.workspace
    clip = _bare_clip(ws, tmp_path / "gone.MP4")  # the file does not exist
    ws.jobs.run_thumbnail(clip.id)

    failed = ws.library.get(clip.id)
    assert failed.thumbnail_status == "failed"
    assert failed.error and failed.error.startswith("thumbnail:")


def test_interrupted_jobs_are_requeued_on_restart(web_app, tmp_path, monkeypatch):
    ws = web_app.state.workspace
    clip = _bare_clip(ws, make_clip(tmp_path / "src" / "resume.MP4"))
    ws.library.update(clip.id, telemetry_status="running")  # as if the app stopped mid-job
    monkeypatch.setattr(jobs_mod, "get_telemetry", lambda path, cache_root: fixture_telemetry())

    ws.resume()
    drain(ws)
    assert ws.library.get(clip.id).telemetry_status == "done"


def test_clip_rows_are_listed_while_jobs_run(web_client, web_app, tmp_path):
    source = make_clip(tmp_path / "rides" / "live.MP4")
    web_client.post("/api/import-folder", json={"path": str(source.parent)})
    statuses = web_client.get("/api/clips").json()[0]
    assert statuses["telemetry_status"] in ("pending", "running", "done")
    wait_for(lambda: web_client.get("/api/clips").json()[0]["proxy_status"] == "done")

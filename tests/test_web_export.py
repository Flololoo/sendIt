"""Task 4.1: export through the API (saved settings and range), job list, cancel, and serving the finished file."""

import subprocess

from web_support import drain, make_clip, wait_for

ON = {
    "overlays": {
        "timestamp": {"enabled": True, "position": "top-left", "size": "M", "settings": {"decimals": 2, "unit": "s"}},
    }
}


def _clip(client, app, tmp_path, seconds=2.0, name="DJI_0080.MP4", config=ON):
    source = make_clip(tmp_path / "rides" / name, seconds=seconds, size="320x240")
    client.post("/api/import-folder", json={"path": str(source.parent)})
    drain(app.state.workspace)
    clip_id = next(c["id"] for c in client.get("/api/clips").json() if c["name"] == name)
    if config is not None:
        assert client.put(f"/api/clips/{clip_id}/config", json=config).status_code == 200
    return clip_id


FINISHED = ("completed", "failed", "cancelled")


def _job_state(client, job_id):
    return next(j for j in client.get("/api/jobs").json() if j["id"] == job_id)


def _wait_for_state(client, job_id, states, timeout=180):
    return wait_for(lambda: (job if (job := _job_state(client, job_id))["state"] in states else None), timeout)


def test_two_second_export_runs_to_completion_through_the_api(web_client, web_app, web_paths, tmp_path):
    clip_id = _clip(web_client, web_app, tmp_path, seconds=2.0)
    started = web_client.post(f"/api/clips/{clip_id}/export", json={"preset": "original"})
    assert started.status_code == 202
    job_id = started.json()["id"]

    job = _wait_for_state(web_client, job_id, FINISHED)
    assert job["state"] == "completed", job["reason"]
    assert job["progress"] == 100.0
    assert job["clip_id"] == clip_id
    assert job["output_url"].startswith("/api/exports/")

    exported = web_paths.exports_dir / job["output_name"]
    assert exported.exists()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(exported)],
        capture_output=True, text=True, check=True,
    ).stdout
    assert abs(float(probe) - 2.0) < 0.2


def test_finished_export_plays_inline_with_range_and_downloads_with_disposition(web_client, web_app, tmp_path):
    clip_id = _clip(web_client, web_app, tmp_path)
    job_id = web_client.post(f"/api/clips/{clip_id}/export", json={}).json()["id"]
    job = _wait_for_state(web_client, job_id, ("completed",))

    inline = web_client.get(job["output_url"])
    assert inline.status_code == 200
    assert inline.headers["content-type"] == "video/mp4"
    assert "content-disposition" not in inline.headers

    ranged = web_client.get(job["output_url"], headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206
    assert len(ranged.content) == 100

    download = web_client.get(job["output_url"] + "?download=1")
    assert download.headers["content-disposition"].startswith("attachment")
    assert job["output_name"] in download.headers["content-disposition"]


def test_export_uses_the_saved_range(web_client, web_app, tmp_path):
    config = {**ON, "range": {"start": 0.5, "end": 1.5}}
    clip_id = _clip(web_client, web_app, tmp_path, seconds=2.0, config=config)
    job_id = web_client.post(f"/api/clips/{clip_id}/export", json={"preset": "original"}).json()["id"]
    job = _wait_for_state(web_client, job_id, FINISHED)
    assert job["state"] == "completed", job["reason"]
    assert (job["start"], job["end"]) == (0.5, 1.5)


def test_cancel_stops_a_running_export_and_lists_no_file(web_client, web_app, web_paths, tmp_path):
    clip_id = _clip(web_client, web_app, tmp_path, seconds=60.0, name="DJI_0081.MP4")
    job_id = web_client.post(f"/api/clips/{clip_id}/export", json={}).json()["id"]
    _wait_for_state(web_client, job_id, ("running",))

    cancel = web_client.post(f"/api/jobs/{job_id}/cancel")
    assert cancel.status_code == 200
    job = _wait_for_state(web_client, job_id, ("cancelled",), timeout=60)
    assert job["output_url"] is None
    assert not any(p.name.startswith("DJI_0081__") for p in web_paths.exports_dir.glob("*.mp4"))
    assert web_client.post(f"/api/jobs/{job_id}/cancel").status_code == 409  # already finished


def test_cancel_a_queued_export_before_it_starts(web_client, web_app, tmp_path):
    long_clip = _clip(web_client, web_app, tmp_path, seconds=20.0, name="DJI_0082.MP4")
    short_clip = _clip(web_client, web_app, tmp_path, seconds=2.0, name="DJI_0083.MP4")
    first = web_client.post(f"/api/clips/{long_clip}/export", json={}).json()["id"]
    second = web_client.post(f"/api/clips/{short_clip}/export", json={}).json()["id"]

    assert web_client.post(f"/api/jobs/{second}/cancel").status_code == 200
    assert _job_state(web_client, second)["state"] == "cancelled"
    web_client.post(f"/api/jobs/{first}/cancel")
    _wait_for_state(web_client, first, FINISHED, timeout=120)


def test_export_without_any_enabled_overlay_is_refused(web_client, web_app, tmp_path):
    clip_id = _clip(web_client, web_app, tmp_path, config={"overlays": {}})
    response = web_client.post(f"/api/clips/{clip_id}/export", json={})
    assert response.status_code == 422
    assert "no overlay is enabled" in response.json()["detail"]


def test_export_with_an_invalid_preset_is_refused(web_client, web_app, tmp_path):
    clip_id = _clip(web_client, web_app, tmp_path)
    response = web_client.post(f"/api/clips/{clip_id}/export", json={"preset": "tiny"})
    assert response.status_code == 422
    assert any(e.startswith("preset:") for e in response.json()["errors"])


def test_export_of_an_unknown_clip_is_404(web_client):
    assert web_client.post("/api/clips/nope/export", json={}).status_code == 404


def test_unknown_job_is_404(web_client):
    assert web_client.post("/api/jobs/nope/cancel").status_code == 404
    assert web_client.get("/api/jobs/nope").status_code == 404


def test_export_file_names_cannot_escape_the_exports_folder(web_client):
    assert web_client.get("/api/exports/..%5Csecret.mp4").status_code in (404, 422)
    assert web_client.get("/api/exports/missing.mp4").status_code == 404

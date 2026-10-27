"""Task 2.4: the clip list with missing-file detection, and removal that never deletes a referenced original."""

from web_support import drain, make_clip


def _import(client, folder):
    return client.post("/api/import-folder", json={"path": str(folder)}).json()


def test_listing_carries_the_library_metadata(web_client, web_app, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_20261026164225_0053_D.MP4", seconds=2, size="320x240")
    _import(web_client, source.parent)
    drain(web_app.state.workspace)

    clip = web_client.get("/api/clips").json()[0]
    assert clip["name"] == "DJI_20261026164225_0053_D.MP4"
    assert clip["origin"] == "reference"
    assert clip["missing"] is False
    assert abs(clip["duration_s"] - 2.0) < 0.2
    assert (clip["display_width"], clip["display_height"]) == (320, 240)
    assert clip["orientation"] == "landscape"
    assert clip["thumbnail_url"] is not None
    assert clip["telemetry_status"] == "done"
    assert clip["telemetry_available"] is False  # a generated clip has no DJI track
    assert clip["camera"] is None
    assert clip["recorded_at"] is None


def test_a_moved_source_is_listed_as_missing_and_blocks_preview_and_export(web_client, web_app, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_0054.MP4")
    _import(web_client, source.parent)
    drain(web_app.state.workspace)
    clip = web_client.get("/api/clips").json()[0]
    web_client.put(
        f"/api/clips/{clip['id']}/config",
        json={"overlays": {"timestamp": {"enabled": True}}},
    )
    source.unlink()

    listed = web_client.get("/api/clips").json()[0]
    assert listed["missing"] is True
    assert listed["playable"] is False
    assert web_client.get(f"/api/clips/{clip['id']}/proxy").status_code == 409
    assert web_client.get(f"/api/clips/{clip['id']}/overlay.png").status_code == 409
    assert web_client.post(f"/api/clips/{clip['id']}/export", json={}).status_code == 409


def test_removing_a_referenced_clip_keeps_the_original_file(web_client, web_app, web_paths, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_0055.MP4")
    _import(web_client, source.parent)
    drain(web_app.state.workspace)
    clip = web_client.get("/api/clips").json()[0]
    cache = web_paths.clip_cache_dir / clip["id"]
    assert cache.exists()  # the generated proxy and thumbnail live here

    response = web_client.delete(f"/api/clips/{clip['id']}")
    assert response.status_code == 204
    assert web_client.get("/api/clips").json() == []
    assert source.exists()  # the original is never deleted
    assert not cache.exists()


def test_removing_an_uploaded_clip_deletes_its_copy_and_cache(web_client, web_app, web_paths, tmp_path):
    source = make_clip(tmp_path / "source" / "DJI_0056.MP4")
    uploaded = web_client.put("/api/uploads/DJI_0056.MP4", content=source.read_bytes()).json()
    drain(web_app.state.workspace)
    clip_id = uploaded["clip"]["id"]
    stored = web_paths.media_dir / "DJI_0056.MP4"
    assert stored.exists()
    assert (web_paths.clip_cache_dir / clip_id).exists()

    assert web_client.delete(f"/api/clips/{clip_id}").status_code == 204
    assert not stored.exists()
    assert not (web_paths.clip_cache_dir / clip_id).exists()
    assert web_client.get("/api/clips").json() == []


def test_removal_keeps_exports(web_client, web_app, web_paths, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_0057.MP4")
    _import(web_client, source.parent)
    drain(web_app.state.workspace)
    web_paths.exports_dir.mkdir(parents=True, exist_ok=True)
    export = web_paths.exports_dir / "DJI_0057__timestamp__0-2.mp4"
    export.write_bytes(b"finished")

    clip_id = web_client.get("/api/clips").json()[0]["id"]
    web_client.delete(f"/api/clips/{clip_id}")
    assert export.read_bytes() == b"finished"


def test_removing_a_clip_removes_its_saved_configuration(web_client, web_app, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_0058.MP4")
    _import(web_client, source.parent)
    drain(web_app.state.workspace)
    clip_id = web_client.get("/api/clips").json()[0]["id"]
    web_client.put(f"/api/clips/{clip_id}/config", json={"mount": "helmet"})

    web_client.delete(f"/api/clips/{clip_id}")
    rows = web_app.state.workspace.db.connection().execute("SELECT COUNT(*) FROM overlay_configs").fetchone()[0]
    assert rows == 0


def test_removing_an_unknown_clip_is_404(web_client):
    assert web_client.delete("/api/clips/does-not-exist").status_code == 404

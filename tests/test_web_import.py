"""Task 2.1: import a folder by reference, with LRF pairing, duplicate detection and no copies."""

import shutil
from pathlib import Path

from web_support import drain, make_clip

LRF_PAIRED = "DJI_20261026155823_0051_D.MP4"
NO_LRF = "DJI_20261026162137_0052_D.MOV"
STRAY_LRF = "DJI_20261026164225_0053_D.LRF"


def _ride_folder(tmp_path: Path) -> Path:
    """A folder of fake-named copies of one tiny generated clip, plus an LRF with no MP4 and a non-video file."""
    source = make_clip(tmp_path / "generated" / "source.mp4")
    folder = tmp_path / "ride"
    folder.mkdir()
    shutil.copy(source, folder / LRF_PAIRED)
    shutil.copy(source, folder / "DJI_20261026155823_0051_D.LRF")
    shutil.copy(source, folder / NO_LRF)
    shutil.copy(source, folder / STRAY_LRF)
    (folder / "notes.txt").write_text("not a clip")
    return folder


def test_one_entry_per_mp4_with_the_lrf_proxy_flagged(web_client, web_app, tmp_path):
    folder = _ride_folder(tmp_path)
    response = web_client.post("/api/import-folder", json={"path": str(folder)})
    assert response.status_code == 200
    added = {clip["name"]: clip for clip in response.json()["added"]}

    assert set(added) == {LRF_PAIRED, NO_LRF}  # the stray LRF and notes.txt are not clips
    assert added[LRF_PAIRED]["proxy_status"] == "lrf"
    assert added[LRF_PAIRED]["proxy_url"] == f"/api/clips/{added[LRF_PAIRED]['id']}/proxy"
    assert added[NO_LRF]["proxy_status"] in ("pending", "running", "done")

    drain(web_app.state.workspace)
    clips = {clip["name"]: clip for clip in web_client.get("/api/clips").json()}
    assert clips[LRF_PAIRED]["proxy_status"] == "lrf"
    assert clips[NO_LRF]["proxy_status"] == "done"
    assert clips[LRF_PAIRED]["playable"] and clips[NO_LRF]["playable"]


def test_import_references_the_originals_and_copies_nothing(web_client, web_app, web_paths, tmp_path):
    folder = _ride_folder(tmp_path)
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.iterdir()}
    response = web_client.post("/api/import-folder", json={"path": str(folder)})
    drain(web_app.state.workspace)

    for clip in response.json()["added"]:
        assert clip["origin"] == "reference"
        assert Path(clip["source_path"]) == (folder / clip["name"]).resolve()
    assert not web_paths.media_dir.exists() or not any(web_paths.media_dir.iterdir())
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in folder.iterdir()}
    assert after == before  # importing neither writes to nor changes the folder


def test_importing_again_reuses_the_entries(web_client, web_app, tmp_path):
    folder = _ride_folder(tmp_path)
    first = web_client.post("/api/import-folder", json={"path": str(folder)}).json()
    second = web_client.post("/api/import-folder", json={"path": str(folder)}).json()
    drain(web_app.state.workspace)

    assert len(first["added"]) == 2
    assert second["added"] == []
    assert {c["id"] for c in second["existing"]} == {c["id"] for c in first["added"]}
    assert len(web_client.get("/api/clips").json()) == 2


def test_no_body_imports_the_default_videos_folder(web_client, web_app, web_paths):
    make_clip(web_paths.videos_dir / "DJI_20261026164225_0053_D.MP4")
    info = web_client.get("/api/workspace").json()
    assert info["default_import_folder"] == str(web_paths.videos_dir)

    body = web_client.post("/api/import-folder").json()
    drain(web_app.state.workspace)
    assert [c["name"] for c in body["added"]] == ["DJI_20261026164225_0053_D.MP4"]


def test_unreadable_video_is_reported_and_not_added(web_client, web_app, tmp_path):
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "DJI_BROKEN.MP4").write_text("this is text, not video")
    body = web_client.post("/api/import-folder", json={"path": str(folder)}).json()

    assert body["added"] == []
    assert body["errors"][0]["file"] == "DJI_BROKEN.MP4"
    assert "not a readable video file" in body["errors"][0]["error"]


def test_missing_folder_is_rejected(web_client, tmp_path):
    response = web_client.post("/api/import-folder", json={"path": str(tmp_path / "nowhere")})
    assert response.status_code == 400
    assert "not a folder" in response.json()["detail"]

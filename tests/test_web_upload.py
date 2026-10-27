"""Task 2.2: streamed PUT uploads, written to .part, renamed on success, removed on disconnect, probed with ffprobe."""

import asyncio
import importlib

from web_support import drain, make_clip, wait_for

service = importlib.import_module("app.workspace.service")


def _files(folder):
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


def _abort_put(app, path: str, first_chunk: bytes, declared: int) -> int:
    """Send a PUT whose body stops after `first_chunk`, then the client disconnects. Returns the response status."""
    messages = [{"type": "http.request", "body": first_chunk, "more_body": True}, {"type": "http.disconnect"}]
    sent: list[dict] = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PUT", "scheme": "http",
        "path": path, "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "headers": [(b"host", b"testserver"), (b"content-length", str(declared).encode())],
        "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_upload_succeeds_and_registers_a_clip(web_client, web_app, web_paths, tmp_path):
    source = make_clip(tmp_path / "source" / "DJI_20261026164225_0053_D.MP4")
    response = web_client.put("/api/uploads/DJI_20261026164225_0053_D.MP4", content=source.read_bytes())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "added"
    assert body["clip"]["origin"] == "upload"
    assert body["clip"]["name"] == "DJI_20261026164225_0053_D.MP4"
    stored = web_paths.media_dir / "DJI_20261026164225_0053_D.MP4"
    assert stored.read_bytes() == source.read_bytes()
    assert _files(web_paths.media_dir) == ["DJI_20261026164225_0053_D.MP4"]  # no .part left behind
    drain(web_app.state.workspace)


def test_chunked_upload_without_a_length_also_works(web_client, web_app, tmp_path):
    source = make_clip(tmp_path / "source" / "chunked.MP4")
    data = source.read_bytes()
    chunks = (data[i:i + 4096] for i in range(0, len(data), 4096))
    response = web_client.put("/api/uploads/chunked.MP4", content=chunks)
    assert response.status_code == 201
    drain(web_app.state.workspace)


def test_same_file_uploaded_twice_is_reported_as_a_duplicate(web_client, web_app, web_paths, tmp_path):
    source = make_clip(tmp_path / "source" / "DJI_0051.MP4")
    first = web_client.put("/api/uploads/DJI_0051.MP4", content=source.read_bytes())
    second = web_client.put("/api/uploads/DJI_0051.MP4", content=source.read_bytes())
    drain(web_app.state.workspace)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert "already in the library" in second.json()["message"]
    assert len(web_client.get("/api/clips").json()) == 1
    assert _files(web_paths.media_dir) == ["DJI_0051.MP4"]


def test_interrupted_upload_leaves_no_file(web_app, web_paths, tmp_path):
    source = make_clip(tmp_path / "source" / "aborted.MP4")
    data = source.read_bytes()
    status = _abort_put(web_app, "/api/uploads/aborted.MP4", data[: len(data) // 2], declared=len(data))

    assert status == 400
    assert _files(web_paths.media_dir) == []
    assert web_app.state.workspace.clips() == []


def test_non_video_upload_is_rejected_with_the_file_named(web_client, web_app, web_paths):
    response = web_client.put("/api/uploads/notes.MP4", content=b"this is not a video")

    assert response.status_code == 422
    body = response.json()
    assert "notes.MP4" in body["detail"]
    assert body["errors"][0].startswith("notes.MP4:")
    assert _files(web_paths.media_dir) == []
    assert web_client.get("/api/clips").json() == []


def test_unsupported_file_type_is_refused(web_client, web_paths):
    response = web_client.put("/api/uploads/readme.txt", content=b"hello")
    assert response.status_code == 415
    assert "readme.txt" in response.json()["detail"]
    assert _files(web_paths.media_dir) == []


def test_lrf_uploaded_after_its_mp4_pairs_with_it(web_client, web_app, tmp_path):
    mp4 = make_clip(tmp_path / "source" / "DJI_0051.MP4")
    lrf = make_clip(tmp_path / "source" / "DJI_0051.LRF", seconds=1.5)
    web_client.put("/api/uploads/DJI_0051.MP4", content=mp4.read_bytes())
    response = web_client.put("/api/uploads/DJI_0051.LRF", content=lrf.read_bytes())
    drain(web_app.state.workspace)

    assert response.status_code == 200
    assert response.json()["status"] == "proxy_paired"
    clips = web_client.get("/api/clips").json()
    assert [c["name"] for c in clips] == ["DJI_0051.MP4"]  # the LRF is never a clip of its own
    assert clips[0]["proxy_status"] == "lrf"
    assert clips[0]["playable"] is True


def test_lrf_uploaded_before_its_mp4_is_held_and_then_paired(web_client, web_app, web_paths, tmp_path):
    mp4 = make_clip(tmp_path / "source" / "DJI_0052.MP4")
    lrf = make_clip(tmp_path / "source" / "DJI_0052.LRF", seconds=1.5)
    held = web_client.put("/api/uploads/DJI_0052.LRF", content=lrf.read_bytes())
    assert held.json()["status"] == "proxy_held"
    assert web_client.get("/api/clips").json() == []

    added = web_client.put("/api/uploads/DJI_0052.MP4", content=mp4.read_bytes())
    drain(web_app.state.workspace)
    assert added.json()["clip"]["proxy_status"] == "lrf"
    assert "DJI_0052.LRF" in _files(web_paths.media_dir)


def test_held_lrf_is_discarded_after_the_hold(web_client, web_app, web_paths, tmp_path, monkeypatch):
    monkeypatch.setattr(service, "HOLD_SECONDS", 0.2)
    lrf = make_clip(tmp_path / "source" / "DJI_0053.LRF", seconds=1)
    web_client.put("/api/uploads/DJI_0053.LRF", content=lrf.read_bytes())
    assert "DJI_0053.LRF" in _files(web_paths.media_dir)

    wait_for(lambda: "DJI_0053.LRF" not in _files(web_paths.media_dir), timeout=10)
    assert web_client.get("/api/clips").json() == []


def test_same_name_different_file_is_stored_under_a_new_name(web_client, web_app, web_paths, tmp_path):
    first = make_clip(tmp_path / "source" / "a.MP4", seconds=2)
    second = make_clip(tmp_path / "source" / "b.MP4", seconds=3)
    web_client.put("/api/uploads/a.MP4", content=first.read_bytes())
    response = web_client.put("/api/uploads/a.MP4", content=second.read_bytes())
    drain(web_app.state.workspace)

    assert response.status_code == 201
    assert _files(web_paths.media_dir) == ["a.MP4", "a_2.MP4"]
    assert [c["name"] for c in web_client.get("/api/clips").json()] == ["a.MP4", "a.MP4"]

"""Task 2.5: the proxy and the thumbnail are served with HTTP Range support."""

from web_support import drain, make_clip


def _uploaded_clip(client, app, tmp_path):
    source = make_clip(tmp_path / "source" / "DJI_0060.MP4", seconds=3)
    body = client.put("/api/uploads/DJI_0060.MP4", content=source.read_bytes()).json()
    drain(app.state.workspace)
    clip = client.get(f"/api/clips/{body['clip']['id']}").json()
    assert clip["proxy_status"] == "done" and clip["thumbnail_status"] == "done"
    return clip


def test_proxy_range_returns_206_with_100_bytes(web_client, web_app, tmp_path):
    clip = _uploaded_clip(web_client, web_app, tmp_path)
    response = web_client.get(clip["proxy_url"], headers={"Range": "bytes=0-99"})

    assert response.status_code == 206
    assert len(response.content) == 100
    assert response.headers["content-range"].startswith("bytes 0-99/")
    assert response.headers["accept-ranges"] == "bytes"


def test_thumbnail_range_returns_206(web_client, web_app, tmp_path):
    clip = _uploaded_clip(web_client, web_app, tmp_path)
    response = web_client.get(clip["thumbnail_url"], headers={"Range": "bytes=0-99"})
    assert response.status_code == 206
    assert len(response.content) == 100


def test_full_proxy_response_is_200_and_accepts_ranges(web_client, web_app, tmp_path):
    clip = _uploaded_clip(web_client, web_app, tmp_path)
    response = web_client.get(clip["proxy_url"])
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert int(response.headers["content-length"]) == len(response.content)


def test_open_ended_range_runs_to_the_end_of_the_file(web_client, web_app, tmp_path):
    clip = _uploaded_clip(web_client, web_app, tmp_path)
    full = web_client.get(clip["proxy_url"]).content
    tail = web_client.get(clip["proxy_url"], headers={"Range": f"bytes={len(full) - 10}-"})
    assert tail.status_code == 206
    assert tail.content == full[-10:]

"""Task 3.2: the overlay layer as a transparent PNG at the requested width, drawn by the export code."""

from io import BytesIO

import numpy as np
from PIL import Image

from web_support import drain, make_clip

ON = {
    "overlays": {
        "timestamp": {"enabled": True, "position": "top-left", "size": "M", "settings": {"decimals": 2, "unit": "s"}},
    }
}


def _clip_with_overlay(client, app, tmp_path, config=ON):
    source = make_clip(tmp_path / "rides" / "DJI_0070.MP4", seconds=2, size="320x240")
    client.post("/api/import-folder", json={"path": str(source.parent)})
    drain(app.state.workspace)
    clip_id = client.get("/api/clips").json()[0]["id"]
    assert client.put(f"/api/clips/{clip_id}/config", json=config).status_code == 200
    return clip_id


def _png(response) -> Image.Image:
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    return Image.open(BytesIO(response.content))


def test_overlay_layer_is_a_png_with_alpha_at_the_requested_width(web_client, web_app, tmp_path):
    clip_id = _clip_with_overlay(web_client, web_app, tmp_path)
    image = _png(web_client.get(f"/api/clips/{clip_id}/overlay.png?t=1&w=200"))

    assert image.mode == "RGBA"
    assert image.width == 200
    assert image.height == 150  # the clip is 320x240, so the frame keeps its aspect ratio
    alpha = np.asarray(image)[:, :, 3]
    assert alpha.max() == 255  # the overlay is drawn
    assert alpha.min() == 0  # and the rest of the frame is transparent


def test_no_enabled_overlay_gives_an_empty_transparent_layer(web_client, web_app, tmp_path):
    clip_id = _clip_with_overlay(web_client, web_app, tmp_path, config={"overlays": {}})
    image = _png(web_client.get(f"/api/clips/{clip_id}/overlay.png?t=1&w=160"))
    assert image.size == (160, 120)
    assert np.asarray(image)[:, :, 3].max() == 0


def test_guides_are_drawn_only_when_asked(web_client, web_app, tmp_path):
    clip_id = _clip_with_overlay(web_client, web_app, tmp_path, config={"overlays": {}})
    plain = _png(web_client.get(f"/api/clips/{clip_id}/overlay.png?t=1&w=200"))
    guided = _png(web_client.get(f"/api/clips/{clip_id}/overlay.png?t=1&w=200&guides=1"))
    assert np.asarray(plain)[:, :, 3].max() == 0
    assert np.asarray(guided)[:, :, 3].max() == 255  # the safe-area boundary


def test_the_layer_changes_with_time(web_client, web_app, tmp_path):
    clip_id = _clip_with_overlay(web_client, web_app, tmp_path)
    early = _png(web_client.get(f"/api/clips/{clip_id}/overlay.png?t=0.2&w=240"))
    late = _png(web_client.get(f"/api/clips/{clip_id}/overlay.png?t=1.7&w=240"))
    assert early.tobytes() != late.tobytes()


def test_out_of_range_time_is_clamped_not_an_error(web_client, web_app, tmp_path):
    clip_id = _clip_with_overlay(web_client, web_app, tmp_path)
    assert web_client.get(f"/api/clips/{clip_id}/overlay.png?t=999&w=120").status_code == 200


def test_width_outside_the_limits_is_refused(web_client, web_app, tmp_path):
    clip_id = _clip_with_overlay(web_client, web_app, tmp_path)
    assert web_client.get(f"/api/clips/{clip_id}/overlay.png?t=0&w=4").status_code == 422

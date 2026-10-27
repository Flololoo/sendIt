"""Task 3.1: overlay registry with availability, and the per-clip configuration (validated, persisted, defaulted)."""

from web_support import drain, make_clip


def _two_clips(client, app, tmp_path):
    source = make_clip(tmp_path / "rides" / "DJI_0061.MP4")
    client.post("/api/import-folder", json={"path": str(source.parent)})
    make_clip(tmp_path / "more" / "DJI_0062.MP4")
    client.post("/api/import-folder", json={"path": str(tmp_path / "more")})
    drain(app.state.workspace)
    clips = {c["name"]: c["id"] for c in client.get("/api/clips").json()}
    return clips["DJI_0061.MP4"], clips["DJI_0062.MP4"]


GOOD = {
    "mount": "helmet",
    "overlays": {
        "timestamp": {
            "enabled": True, "position": "top-right", "size": "L", "settings": {"decimals": 0, "unit": "ms"},
        },
    },
    "range": {"start": 0.5, "end": 1.5},
}


def test_overlay_registry_lists_settings_and_availability(web_client, web_app, tmp_path):
    clip_id, _ = _two_clips(web_client, web_app, tmp_path)
    body = web_client.get(f"/api/overlays?clip={clip_id}").json()

    assert body["mounts"] == ["helmet", "bike"]
    overlays = {o["id"]: o for o in body["overlays"]}
    assert overlays["timestamp"]["available"] is True
    assert {s["key"] for s in overlays["timestamp"]["settings"]} == {"decimals", "unit"}
    telemetry = overlays["telemetry_stub"]
    assert telemetry["available"] is False
    assert telemetry["reason"] == "no telemetry"


def test_overlay_registry_without_a_clip_marks_everything_available(web_client, web_app, tmp_path):
    _two_clips(web_client, web_app, tmp_path)
    overlays = web_client.get("/api/overlays").json()["overlays"]
    assert all(o["available"] for o in overlays)


def test_unconfigured_clip_defaults_to_the_bike_mount_and_no_overlays(web_client, web_app, tmp_path):
    clip_id, _ = _two_clips(web_client, web_app, tmp_path)
    body = web_client.get(f"/api/clips/{clip_id}/config").json()
    assert body["mount"] == "bike"
    assert body["source"] == "default"
    assert body["overlays"]["timestamp"]["enabled"] is False
    assert body["range"] == {"start": None, "end": None}


def test_saved_configuration_is_returned_with_defaults_filled_in(web_client, web_app, tmp_path):
    clip_id, _ = _two_clips(web_client, web_app, tmp_path)
    saved = web_client.put(f"/api/clips/{clip_id}/config", json=GOOD)
    assert saved.status_code == 200

    body = web_client.get(f"/api/clips/{clip_id}/config").json()
    assert body["source"] == "saved"
    assert body["mount"] == "helmet"
    assert body["range"] == {"start": 0.5, "end": 1.5}
    timestamp = body["overlays"]["timestamp"]
    assert timestamp == {
        "enabled": True, "position": "top-right", "size": "L", "settings": {"decimals": 0, "unit": "ms"},
    }
    assert body["overlays"]["telemetry_stub"]["enabled"] is False  # absent entries are off, with defaults filled


def test_invalid_setting_is_refused_and_names_the_field(web_client, web_app, tmp_path):
    clip_id, _ = _two_clips(web_client, web_app, tmp_path)
    bad = {"overlays": {"timestamp": {"enabled": True, "settings": {"decimals": 9}}}}
    response = web_client.put(f"/api/clips/{clip_id}/config", json=bad)

    assert response.status_code == 422
    assert any("timestamp.settings.decimals" in e for e in response.json()["errors"])
    assert web_client.get(f"/api/clips/{clip_id}/config").json()["source"] == "default"


def test_unknown_mount_is_refused(web_client, web_app, tmp_path):
    clip_id, _ = _two_clips(web_client, web_app, tmp_path)
    response = web_client.put(f"/api/clips/{clip_id}/config", json={"mount": "handlebar"})
    assert response.status_code == 422
    assert any(e.startswith("mount:") for e in response.json()["errors"])


def test_invalid_range_is_refused(web_client, web_app, tmp_path):
    clip_id, _ = _two_clips(web_client, web_app, tmp_path)
    response = web_client.put(f"/api/clips/{clip_id}/config", json={"range": {"start": 1.5, "end": 0.5}})
    assert response.status_code == 422
    assert any(e.startswith("range:") for e in response.json()["errors"])


def test_configuration_survives_an_app_restart(make_web_app, tmp_path):
    from fastapi.testclient import TestClient

    with TestClient(make_web_app()) as first:
        source = make_clip(tmp_path / "rides" / "DJI_0063.MP4")
        first.post("/api/import-folder", json={"path": str(source.parent)})
        drain(first.app.state.workspace)
        clip_id = first.get("/api/clips").json()[0]["id"]
        first.put(f"/api/clips/{clip_id}/config", json=GOOD)
        before = first.get(f"/api/clips/{clip_id}/config").json()

    with TestClient(make_web_app()) as second:
        after = second.get(f"/api/clips/{clip_id}/config").json()
    assert after["source"] == "saved"
    assert after["overlays"] == before["overlays"]
    assert after["mount"] == before["mount"] == "helmet"
    assert after["range"] == before["range"]


def test_a_new_clip_starts_from_the_last_saved_settings_but_not_its_range(web_client, web_app, tmp_path):
    first_id, second_id = _two_clips(web_client, web_app, tmp_path)
    web_client.put(f"/api/clips/{first_id}/config", json=GOOD)

    body = web_client.get(f"/api/clips/{second_id}/config").json()
    assert body["source"] == "last_used"
    assert body["mount"] == "helmet"
    assert body["overlays"]["timestamp"]["enabled"] is True
    assert body["range"] == {"start": None, "end": None}

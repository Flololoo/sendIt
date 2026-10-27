import pytest

from overlay_fixtures import TelemetryOverlay, TimestampOverlay, make_clip

from app.overlays.registry import NO_TELEMETRY, OverlayRegistry


def test_register_and_list_in_order():
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    reg.register(TelemetryOverlay())
    assert [o.id for o in reg.overlays()] == ["timestamp", "telemetry_stub"]
    assert reg.get("timestamp").name == "Timestamp"
    assert reg.get("missing") is None


def test_duplicate_id_rejected():
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    with pytest.raises(ValueError, match="timestamp"):
        reg.register(TimestampOverlay())


def test_telemetry_overlay_unavailable_without_telemetry():
    reg = OverlayRegistry()
    tel = reg.register(TelemetryOverlay())
    result = reg.availability(tel, make_clip(with_telemetry=False))
    assert result.available is False
    assert result.reason == NO_TELEMETRY == "no telemetry"


def test_telemetry_overlay_available_with_telemetry():
    reg = OverlayRegistry()
    tel = reg.register(TelemetryOverlay())
    assert reg.availability(tel, make_clip(with_telemetry=True)).available is True


def test_overlay_without_telemetry_requirement_always_available():
    reg = OverlayRegistry()
    ts = reg.register(TimestampOverlay())
    assert reg.availability(ts, make_clip(with_telemetry=False)).available is True


def test_overlays_for_clip_reports_each_overlay():
    reg = OverlayRegistry()
    reg.register(TimestampOverlay())
    reg.register(TelemetryOverlay())
    rows = reg.overlays_for(make_clip(with_telemetry=False))
    assert [(o.id, a.available) for o, a in rows] == [("timestamp", True), ("telemetry_stub", False)]
    assert rows[1][1].reason == "no telemetry"

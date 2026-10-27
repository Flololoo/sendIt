import pytest

from app.telemetry.extract import build_metadata
from helpers import load_fixture_parts


def test_fixture_reports_portrait_4k_display_size(fixture_tel):
    meta = fixture_tel.meta
    assert (meta.width, meta.height) == (3840, 2160)
    assert meta.rotation == -90
    assert (meta.display_width, meta.display_height) == (2160, 3840)
    assert meta.orientation == "portrait"


def test_fixture_reports_no_gps(fixture_tel):
    assert fixture_tel.meta.has_gps is False


def test_fixture_reports_device_header_and_timing(fixture_tel):
    meta = fixture_tel.meta
    assert meta.telemetry_available is True
    assert meta.model == "DJI OsmoAction4"
    assert meta.serial == "6S6VNCG00A0LN8"
    assert meta.firmware == "10.00.42.03"
    assert meta.proto_schema == "dvtm_ac203.proto"
    assert meta.fps == pytest.approx(59.94, abs=0.01)
    assert meta.duration_s == pytest.approx(756.372283)
    assert meta.start_utc == "2026-10-26T13:58:24+00:00"


def test_landscape_when_unrotated():
    _, _, _, summary = load_fixture_parts()
    summary = {**summary, "rotation": 0}
    meta = build_metadata(summary, {}, source="x", telemetry_available=False, has_gps=False)
    assert (meta.display_width, meta.display_height) == (3840, 2160)
    assert meta.orientation == "landscape"


def test_metadata_round_trips_through_dict(fixture_tel):
    from app.telemetry.model import Metadata

    assert Metadata.from_dict(fixture_tel.meta.to_dict()) == fixture_tel.meta

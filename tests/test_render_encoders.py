import logging
import shutil

import pytest

from app.render import encoders
from app.render.encoders import ENCODER_ARGS, ENCODER_ORDER, EncoderError, select_encoder


def _probe_from(working: set[str], calls: list[str]):
    def probe(name: str) -> bool:
        calls.append(name)
        return name in working

    return probe


@pytest.mark.parametrize(
    "working, expected",
    [
        ({"hevc_nvenc", "h264_nvenc", "libx264"}, "hevc_nvenc"),
        ({"h264_nvenc", "libx264"}, "h264_nvenc"),
        ({"libx264"}, "libx264"),
    ],
)
def test_first_working_encoder_is_chosen(working, expected):
    assert select_encoder(_probe_from(working, [])) == expected


def test_probe_stops_at_first_success():
    calls: list[str] = []
    select_encoder(_probe_from({"hevc_nvenc", "libx264"}, calls))
    assert calls == ["hevc_nvenc"]


def test_probe_falls_back_in_order():
    calls: list[str] = []
    select_encoder(_probe_from({"libx264"}, calls))
    assert calls == list(ENCODER_ORDER)


def test_no_working_encoder_raises():
    with pytest.raises(EncoderError, match="no usable video encoder"):
        select_encoder(_probe_from(set(), []))


def test_chosen_encoder_is_logged(caplog):
    with caplog.at_level(logging.INFO, logger="app.render.encoders"):
        select_encoder(_probe_from({"h264_nvenc"}, []))
    assert "video encoder: h264_nvenc" in caplog.text


def test_startup_encoder_probes_once(monkeypatch):
    calls: list[str] = []

    def fake_select(probe=None):
        calls.append("select")
        return "libx264"

    monkeypatch.setattr(encoders, "_chosen", None)
    monkeypatch.setattr(encoders, "select_encoder", fake_select)
    assert encoders.startup_encoder() == "libx264"
    assert encoders.startup_encoder() == "libx264"
    assert calls == ["select"]


@pytest.mark.parametrize("name", ENCODER_ORDER)
def test_each_candidate_has_codec_arguments(name):
    assert ENCODER_ARGS[name][:2] == ("-c:v", name)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_real_probe_accepts_libx264():
    assert encoders.probe_encoder("libx264") is True

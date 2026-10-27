"""Runs against the real clips in videos/. Skipped when those files are absent."""

from pathlib import Path

import pytest

from app.telemetry import ffmpeg_io
from app.telemetry.extract import extract_telemetry

VIDEOS = Path(__file__).resolve().parents[1] / "videos"
EXPECTED_SAMPLES = {
    "DJI_20261026155823_0051_D.MP4": 45337,
    "DJI_20261026162137_0052_D.MP4": 47618,
    "DJI_20261026164225_0053_D.MP4": 57093,
}


@pytest.mark.parametrize("name", sorted(EXPECTED_SAMPLES))
def test_clip_sample_count_matches_data_stream(name):
    path = VIDEOS / name
    if not path.exists():
        pytest.skip(f"{path} not present")

    info = ffmpeg_io.probe(path)
    index = ffmpeg_io.find_telemetry_stream(info)
    assert index is not None, "DJI meta stream not found"
    data_stream = next(s for s in info["streams"] if s["index"] == index)
    nb_frames = int(data_stream["nb_frames"])
    assert nb_frames == EXPECTED_SAMPLES[name]

    tel = extract_telemetry(path)
    assert len(tel) == nb_frames
    assert tel.skipped == 0
    assert tel.meta.has_gps is False
    assert tel.samples.t[0] == 0.0
    frame = 1001 / 60000  # one frame at 59.94 fps
    assert abs(tel.samples.t[-1] - tel.meta.duration_s) <= frame + 1e-6

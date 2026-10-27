import os

import numpy as np
import pytest

from app.telemetry import cache, ffmpeg_io
from helpers import fixture_telemetry


@pytest.fixture
def counting_extract(monkeypatch):
    """Replace the real extraction with the fixture decode and count calls.

    Any shell-out to ffmpeg or ffprobe during a cache hit fails the test.
    """
    calls = {"n": 0}

    def fake_extract(path):
        calls["n"] += 1
        return fixture_telemetry()

    monkeypatch.setattr(cache, "extract_telemetry", fake_extract)

    def no_tools(*args, **kwargs):
        raise AssertionError("ffmpeg/ffprobe must not run on a cache hit")

    monkeypatch.setattr(ffmpeg_io, "_run", no_tools)
    return calls


def _same_telemetry(a, b):
    assert a.meta == b.meta
    assert a.skipped == b.skipped
    for name in ("t", "quat", "accel", "iso", "shutter_s", "wb_k"):
        np.testing.assert_array_equal(getattr(a.samples, name), getattr(b.samples, name))


def test_second_call_is_served_from_cache(tmp_path, counting_extract):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"x" * 1000)
    root = tmp_path / "cache"

    first = cache.get_telemetry(video, cache_root=root)
    second = cache.get_telemetry(video, cache_root=root)

    assert counting_extract["n"] == 1
    _same_telemetry(first, second)
    assert (root / "clip" / "meta.json").exists()
    assert (root / "clip" / "telemetry.npz").exists()


def test_touching_source_triggers_reextraction(tmp_path, counting_extract):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"x" * 1000)
    root = tmp_path / "cache"
    cache.get_telemetry(video, cache_root=root)

    st = video.stat()
    os.utime(video, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    cache.get_telemetry(video, cache_root=root)
    assert counting_extract["n"] == 2


def test_changed_size_triggers_reextraction(tmp_path, counting_extract):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"x" * 1000)
    root = tmp_path / "cache"
    cache.get_telemetry(video, cache_root=root)

    video.write_bytes(b"x" * 2000)
    cache.get_telemetry(video, cache_root=root)
    assert counting_extract["n"] == 2


def test_use_cache_false_neither_reads_nor_writes(tmp_path, counting_extract):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"x" * 1000)
    root = tmp_path / "cache"
    cache.get_telemetry(video, use_cache=False, cache_root=root)
    cache.get_telemetry(video, use_cache=False, cache_root=root)
    assert counting_extract["n"] == 2
    assert not root.exists()


def test_corrupt_cache_is_replaced(tmp_path, counting_extract):
    video = tmp_path / "clip.MP4"
    video.write_bytes(b"x" * 1000)
    root = tmp_path / "cache"
    cache.get_telemetry(video, cache_root=root)
    (root / "clip" / "meta.json").write_text("{not json", encoding="utf-8")
    cache.get_telemetry(video, cache_root=root)
    assert counting_extract["n"] == 2

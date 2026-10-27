"""On-disk cache of decoded telemetry.

Layout: data/cache/<video-id>/telemetry.npz (sample arrays) and meta.json (metadata
plus the source key). The cache is valid while the source's absolute path, size and
mtime match what was recorded. meta.json is written last, so an interrupted write
leaves no valid entry behind.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .extract import extract_telemetry
from .model import Metadata, Samples, Telemetry

CACHE_VERSION = 1
DEFAULT_CACHE_ROOT = Path(__file__).resolve().parents[2] / "data" / "cache"
SAMPLE_FIELDS = ("t", "quat", "accel", "iso", "shutter_s", "wb_k")


def _entry_dir(video: Path, cache_root: Path) -> Path:
    return cache_root / video.stem


def _source_key(video: Path) -> dict:
    stat = video.stat()
    return {
        "version": CACHE_VERSION,
        "source": str(video.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def load_cached(video: Path, cache_root: Path = DEFAULT_CACHE_ROOT) -> Telemetry | None:
    """Return the cached telemetry if it matches the current source file, else None."""
    entry = _entry_dir(video, cache_root)
    try:
        info = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    key = _source_key(video)
    if any(info.get(name) != key[name] for name in key):
        return None
    try:
        with np.load(entry / "telemetry.npz") as data:
            samples = Samples(**{name: data[name] for name in SAMPLE_FIELDS})
    except (OSError, ValueError, KeyError):
        return None
    return Telemetry(samples=samples, meta=Metadata.from_dict(info["metadata"]), skipped=int(info["skipped"]))


def save_cached(video: Path, telemetry: Telemetry, cache_root: Path = DEFAULT_CACHE_ROOT) -> None:
    entry = _entry_dir(video, cache_root)
    entry.mkdir(parents=True, exist_ok=True)
    arrays = {name: getattr(telemetry.samples, name) for name in SAMPLE_FIELDS}
    np.savez_compressed(entry / "telemetry.npz", **arrays)
    info = {
        **_source_key(video),
        "skipped": telemetry.skipped,
        "metadata": telemetry.meta.to_dict(),
    }
    (entry / "meta.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def get_telemetry(
    path: str | Path,
    *,
    use_cache: bool = True,
    cache_root: Path = DEFAULT_CACHE_ROOT,
) -> Telemetry:
    """Return decoded telemetry for a video, extracting it only when no valid cache exists."""
    video = Path(path)
    if use_cache:
        cached = load_cached(video, cache_root)
        if cached is not None:
            return cached
    telemetry = extract_telemetry(video)
    if use_cache:
        save_cached(video, telemetry, cache_root)
    return telemetry

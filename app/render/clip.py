"""Clip inputs shared by preview and export."""

from __future__ import annotations

from pathlib import Path

from app.overlays.contract import ClipContext, Mount
from app.telemetry import get_telemetry
from app.telemetry.cache import DEFAULT_CACHE_ROOT


def load_clip(path: str | Path, mount: Mount = "bike", *, cache_root: Path = DEFAULT_CACHE_ROOT) -> ClipContext:
    """Return the overlay clip context for an MP4, with telemetry from the cache when present."""
    path = Path(path)
    tel = get_telemetry(path, cache_root=cache_root)
    telemetry = tel if tel.meta.telemetry_available else None
    return ClipContext(path=path, meta=tel.meta, telemetry=telemetry, mount=mount)


def preview_source(mp4: str | Path) -> Path:
    """Return the LRF next to the MP4 (same stem) when it exists, else the MP4 itself."""
    mp4 = Path(mp4)
    for suffix in (".LRF", ".lrf"):
        lrf = mp4.with_suffix(suffix)
        if lrf.exists():
            return lrf
    return mp4

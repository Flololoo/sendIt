"""Output file names for exports. An existing file is never overwritten."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

DEFAULT_EXPORTS_DIR = Path(__file__).resolve().parents[2] / "exports"


def export_stem(clip: Path, overlay_ids: Sequence[str], start: float, end: float) -> str:
    """Return `<clip-stem>__<overlay-ids>__<start>-<end>`, with ids joined by '+'."""
    return f"{clip.stem}__{'+'.join(overlay_ids)}__{_seconds(start)}-{_seconds(end)}"


def _seconds(value: float) -> str:
    return f"{round(value, 3):g}"


def reserve_output(exports_dir: Path, stem: str, suffix: str = ".mp4") -> Path:
    """Create an empty file for `stem` and return its path, adding _2, _3 ... if the name is taken.

    The file is created exclusively, so two exports never pick the same name.
    The caller replaces the placeholder with the rendered output or deletes it on failure.
    """
    exports_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        name = f"{stem}{suffix}" if n == 1 else f"{stem}_{n}{suffix}"
        path = exports_dir / name
        try:
            with open(path, "xb"):
                pass
        except FileExistsError:
            n += 1
            continue
        return path

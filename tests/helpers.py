import json
from pathlib import Path

from app.telemetry.extract import build_telemetry

FIXTURES = Path(__file__).parent / "fixtures"
STEM = "0051"


def load_fixture_parts():
    """Return (raw payload, packet pts seconds, packet sizes, video summary) for the cut-down clip."""
    raw = (FIXTURES / f"djmd_{STEM}_raw.bin").read_bytes()
    packets = json.loads((FIXTURES / f"djmd_{STEM}_packets.json").read_text(encoding="utf-8"))
    summary = json.loads((FIXTURES / f"video_{STEM}.json").read_text(encoding="utf-8"))
    return raw, packets["pts_s"], packets["sizes"], summary


def fixture_telemetry(raw=None, pts=None, sizes=None):
    base_raw, base_pts, base_sizes, summary = load_fixture_parts()
    return build_telemetry(
        base_raw if raw is None else raw,
        base_pts if pts is None else pts,
        base_sizes if sizes is None else sizes,
        summary,
        source=f"DJI_20261026155823_{STEM}_D.MP4",
    )

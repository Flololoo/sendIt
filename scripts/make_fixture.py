"""Cut a small telemetry fixture out of a DJI clip for the unit tests.

Writes into tests/fixtures/:
  djmd_<id>_raw.bin       raw payload of the first N djmd packets
  djmd_<id>_packets.json  pts_time (seconds) and size of each of those packets
  video_<id>.json         ffprobe summary of the video stream (size, rotation, fps, ...)

Usage:
  python scripts/make_fixture.py [clip] [--count 300]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.telemetry import ffmpeg_io  # noqa: E402

DEFAULT_CLIP = ROOT / "videos" / "DJI_20261026155823_0051_D.MP4"
FIXTURE_DIR = ROOT / "tests" / "fixtures"


def make_fixture(clip: Path, count: int, out_dir: Path) -> list[Path]:
    info = ffmpeg_io.probe(clip)
    index = ffmpeg_io.find_telemetry_stream(info)
    if index is None:
        raise SystemExit(f"{clip.name}: no DJI meta stream found")

    pts, sizes = ffmpeg_io.read_packet_times_and_sizes(clip, index)
    raw = ffmpeg_io.read_raw_packets(clip, index)
    if int(sizes.sum()) != len(raw):
        raise SystemExit("raw dump does not match the packet sizes")

    pts = pts[:count]
    sizes = sizes[:count]
    raw = raw[: int(sizes.sum())]
    stem = clip.stem.split("_")[-2]  # "0051"

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"djmd_{stem}_raw.bin"
    packets_path = out_dir / f"djmd_{stem}_packets.json"
    video_path = out_dir / f"video_{stem}.json"

    raw_path.write_bytes(raw)
    packets_path.write_text(
        json.dumps(
            {
                "source": clip.name,
                "telemetry_stream_index": index,
                "pts_s": [float(p) for p in pts],
                "sizes": [int(s) for s in sizes],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    summary = ffmpeg_io.video_summary(info)
    summary["source"] = clip.name
    summary["telemetry_stream_index"] = index
    video_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return [raw_path, packets_path, video_path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("clip", nargs="?", type=Path, default=DEFAULT_CLIP)
    parser.add_argument("--count", type=int, default=300, help="number of djmd packets to keep")
    parser.add_argument("--out", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args()
    ffmpeg_io.require_ffmpeg()
    for path in make_fixture(args.clip, args.count, args.out):
        print(f"{path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()

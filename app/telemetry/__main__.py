"""Command line: python -m app.telemetry <video> [--csv out.csv] [--no-cache]"""

from __future__ import annotations

import argparse
import sys

from .cache import get_telemetry
from .export import export_csv
from .ffmpeg_io import MissingToolError, ToolError


def _print_report(tel) -> None:
    m = tel.meta
    fps = f"{m.fps:.3f}" if m.fps else "unknown"
    print(f"Source:        {m.source}")
    print(f"Camera:        {m.model or 'unknown'}  serial {m.serial or 'unknown'}  firmware {m.firmware or 'unknown'}")
    print(f"Stored size:   {m.width}x{m.height} @ {fps} fps, rotation {m.rotation}")
    print(f"Display:       {m.display_width}x{m.display_height} ({m.orientation})")
    print(f"Duration:      {m.duration_s:.3f} s")
    print(f"Start (UTC):   {m.start_utc or 'unknown'}")
    print(f"GPS:           {'present' if m.has_gps else 'unavailable'}")
    if not m.telemetry_available:
        print("Telemetry:     no DJI meta track in this file")
    print(f"Samples:       {len(tel)}")
    print(f"Skipped:       {tel.skipped} undecodable record(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.telemetry", description="Read DJI Osmo Action telemetry.")
    parser.add_argument("video", help="path to an MP4 or LRF clip")
    parser.add_argument("--csv", metavar="OUT", help="also write the samples to this CSV file")
    parser.add_argument("--no-cache", action="store_true", help="ignore and do not write the telemetry cache")
    args = parser.parse_args(argv)

    try:
        tel = get_telemetry(args.video, use_cache=not args.no_cache)
    except MissingToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (ToolError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_report(tel)
    if args.csv:
        rows = export_csv(tel, args.csv)
        print(f"CSV:           {rows} row(s) written to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

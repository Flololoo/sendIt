"""Command line: python -m app.render export <clip> --overlay <id> [...] [--start S] [--end E] [--preset original|social] [--mount helmet|bike]

Runs the export through the same ExportQueue the app uses, and waits for it to finish.
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import sys
import time
from pathlib import Path

from app.overlays.registry import default_registry

from .export import PRESETS
from .queue import DEFAULT_JOBS_PATH, ExportQueue

TEST_OVERLAY_FILE = Path(__file__).resolve().parents[2] / "tests" / "overlay_fixtures.py"
POLL_SECONDS = 0.5
PROGRESS_STEP = 5  # print a progress line every this many percent
TERMINAL = ("completed", "failed", "cancelled")


def _register_test_overlay() -> None:
    """Register the test-only TimestampOverlay from tests/overlay_fixtures.py. Hidden debug aid."""
    if default_registry.get("timestamp") is not None:
        return
    spec = importlib.util.spec_from_file_location("overlay_fixtures", TEST_OVERLAY_FILE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    default_registry.register(module.TimestampOverlay())


def _export(args: argparse.Namespace) -> int:
    if args.with_test_overlay:
        _register_test_overlay()
    queue = ExportQueue(jobs_path=args.jobs_file)
    config = {overlay_id: {} for overlay_id in args.overlay}
    started = time.monotonic()
    job_id = queue.submit(
        args.clip, config, preset=args.preset, start=args.start, end=args.end, mount=args.mount,
    )
    print(f"job {job_id} queued")
    last_step = -1
    try:
        while True:
            job = queue.wait(job_id, timeout=POLL_SECONDS)
            if job.state in TERMINAL:
                break
            step = int(job.progress) // PROGRESS_STEP
            if job.state == "running" and step != last_step:
                last_step = step
                eta = "" if job.eta_s is None else f"  ETA {job.eta_s:.0f} s"
                print(f"running {job.progress:5.1f}%{eta}", flush=True)
    except KeyboardInterrupt:
        queue.cancel(job_id)
        queue.wait(job_id, timeout=None)
        print("cancelled", file=sys.stderr)
        return 130
    finally:
        queue.close()

    elapsed = time.monotonic() - started
    if job.state == "completed":
        print(f"completed in {elapsed:.1f} s: {job.output}")
        return 0
    if job.state == "cancelled":
        print("error: export cancelled", file=sys.stderr)
    else:
        print(f"error: export failed: {job.reason}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.render", description="Render clips with overlays burned in.")
    commands = parser.add_subparsers(dest="command", required=True)

    export_cmd = commands.add_parser("export", help="render a clip with overlays burned in")
    export_cmd.add_argument("clip", help="path to an MP4 clip")
    export_cmd.add_argument("--overlay", action="append", required=True, metavar="ID",
                            help="overlay id to burn in (repeatable)")
    export_cmd.add_argument("--start", type=float, metavar="S", help="start of the range in seconds")
    export_cmd.add_argument("--end", type=float, metavar="E", help="end of the range in seconds")
    export_cmd.add_argument("--preset", choices=PRESETS, default="original", help="output resolution preset")
    export_cmd.add_argument("--mount", choices=("helmet", "bike"), default="bike", help="how the camera is mounted")
    export_cmd.add_argument("--jobs-file", type=Path, default=DEFAULT_JOBS_PATH, metavar="PATH",
                            help="where the job history is kept")
    export_cmd.add_argument("--with-test-overlay", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    return _export(args)


if __name__ == "__main__":
    sys.exit(main())

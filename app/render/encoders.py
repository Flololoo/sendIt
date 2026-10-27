"""Video encoder choice: probes hevc_nvenc, h264_nvenc and libx264 in that order, once."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

log = logging.getLogger(__name__)

ENCODER_ORDER: tuple[str, ...] = ("hevc_nvenc", "h264_nvenc", "libx264")

# Constant-quality output arguments per encoder.
ENCODER_ARGS: dict[str, tuple[str, ...]] = {
    "hevc_nvenc": ("-c:v", "hevc_nvenc", "-preset", "p5", "-cq", "20", "-b:v", "0"),
    "h264_nvenc": ("-c:v", "h264_nvenc", "-preset", "p5", "-cq", "20", "-b:v", "0"),
    "libx264": ("-c:v", "libx264", "-preset", "medium", "-crf", "18"),
}


class EncoderError(RuntimeError):
    """Raised when none of the candidate encoders works."""


def is_hevc(encoder: str) -> bool:
    """Return True for HEVC encoders, which need the hvc1 tag for Apple and Instagram playback."""
    return encoder.startswith("hevc_") or encoder == "libx265"


def probe_encoder(name: str) -> bool:
    """Return True if ffmpeg can encode one frame with `name`."""
    cmd = [
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
        "-frames:v", "1", "-c:v", name, "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def select_encoder(probe: Callable[[str], bool] = probe_encoder) -> str:
    """Return the first encoder in ENCODER_ORDER that `probe` accepts, and log the choice."""
    for name in ENCODER_ORDER:
        if probe(name):
            log.info("video encoder: %s", name)
            return name
        log.warning("video encoder %s is not usable, trying the next one", name)
    raise EncoderError(f"no usable video encoder (tried {', '.join(ENCODER_ORDER)})")


_chosen: str | None = None


def startup_encoder() -> str:
    """Return the encoder chosen by probing, probing once on first use."""
    global _chosen
    if _chosen is None:
        _chosen = select_encoder()
    return _chosen

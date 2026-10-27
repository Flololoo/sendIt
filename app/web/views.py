"""JSON shapes the frontend receives for clips, overlay configurations and export jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.overlays.registry import OverlayRegistry
from app.render.queue import Job
from app.workspace import Clip, ConfigView
from app.workspace.library import DONE, LRF


def clip_json(clip: Clip, missing: bool) -> dict[str, Any]:
    meta = clip.meta
    thumbnail = clip.thumbnail_status == DONE
    proxy_ready = clip.proxy_status in (DONE, LRF) and bool(clip.proxy_path) and Path(clip.proxy_path).exists()
    return {
        "id": clip.id,
        "name": clip.name,
        "origin": clip.origin,
        "source_path": clip.source_path,
        "missing": missing,
        "size": clip.size,
        "duration_s": meta.duration_s,
        "display_width": meta.display_width,
        "display_height": meta.display_height,
        "orientation": meta.orientation,
        "recorded_at": meta.start_utc,
        "camera": meta.model,
        "telemetry_status": clip.telemetry_status,
        "telemetry_available": meta.telemetry_available if clip.telemetry_status == DONE else None,
        "thumbnail_status": clip.thumbnail_status,
        "thumbnail_url": f"/api/clips/{clip.id}/thumbnail" if thumbnail else None,
        "proxy_status": clip.proxy_status,
        "proxy_progress": clip.proxy_progress,
        "proxy_url": f"/api/clips/{clip.id}/proxy" if proxy_ready else None,
        "playable": proxy_ready and not missing,
        "error": clip.error,
        "added_at": clip.added_at,
    }


def resolved_overlays(registry: OverlayRegistry, stored: dict[str, Any]) -> dict[str, Any]:
    """Every registered overlay with its effective values, using the same defaults the engine applies."""
    out: dict[str, Any] = {}
    for overlay in registry.overlays():
        entry = stored.get(overlay.id)
        if entry is None:
            out[overlay.id] = {
                "enabled": False,
                "position": overlay.default_position,
                "size": overlay.default_size,
                "settings": {s.key: s.default for s in overlay.settings},
            }
            continue
        given = entry.get("settings", {})
        out[overlay.id] = {
            "enabled": entry.get("enabled", True),
            "position": entry.get("position", overlay.default_position),
            "size": entry.get("size", overlay.default_size),
            "settings": {s.key: given.get(s.key, s.default) for s in overlay.settings},
        }
    return out


def config_json(view: ConfigView, registry: OverlayRegistry) -> dict[str, Any]:
    return {
        "clip_id": view.clip_id,
        "mount": view.mount,
        "overlays": resolved_overlays(registry, view.overlays),
        "range": {"start": view.range_start, "end": view.range_end},
        "updated_at": view.updated_at,
        "source": view.source,
    }


def job_json(job: Job, clip_id: str | None) -> dict[str, Any]:
    output_name = Path(job.output).name if job.output else None
    ready = job.state == "completed" and job.output is not None and Path(job.output).exists()
    return {
        "id": job.id,
        "clip_id": clip_id,
        "clip_name": Path(job.clip).name,
        "state": job.state,
        "progress": job.progress,
        "eta_s": job.eta_s,
        "preset": job.preset,
        "start": job.start,
        "end": job.end,
        "mount": job.mount,
        "output_name": output_name if ready else None,
        "output_url": f"/api/exports/{output_name}" if ready else None,
        "reason": job.reason,
        "submitted_at": job.submitted_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }

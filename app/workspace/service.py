"""The workspace: folder import, uploads, clip removal, overlay configuration and export inputs.

The web layer talks only to this class. It combines the library tables and background jobs with
the overlay and render engine. Validation and drawing go through the engine's own functions.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, get_args

from PIL import Image

from app.overlays.config import ConfigError, OverlayConfig, validate_config
from app.overlays.contract import POSITIONS, SIZES, ClipContext, Mount, Overlay
from app.overlays.layer import plan_layer, render_layer, union_box
from app.overlays.registry import Availability, OverlayRegistry
from app.render.clip import load_clip
from app.render.export import PRESETS, ExportError, resolve_range
from app.render.preview import draw_safe_guides
from app.telemetry import Metadata, Samples, Telemetry
from app.telemetry.ffmpeg_io import MissingToolError, ToolError, require_ffmpeg

from . import media
from .db import Database
from .errors import BadRequest, Conflict, Invalid, NotFound, Unavailable, Unsupported
from .jobs import Jobs
from .library import FAILED, LRF, PENDING, RUNNING, Clip, Library
from .paths import WorkspacePaths

log = logging.getLogger(__name__)

MOUNTS: tuple[str, ...] = get_args(Mount)
DEFAULT_MOUNT = "bike"
ORIGIN_UPLOAD = "upload"
ORIGIN_REFERENCE = "reference"
REFERENCE_SUFFIXES = (".mp4", ".mov")
UPLOAD_SUFFIXES = (".mp4", ".mov", ".lrf")
HOLD_SECONDS = 60  # an LRF with no matching MP4 is kept this long, then discarded


@dataclass(frozen=True)
class ImportResult:
    folder: str
    added: list[Clip]
    existing: list[Clip]
    errors: list[dict[str, str]]


@dataclass(frozen=True)
class UploadTarget:
    name: str  # the file name as the user gave it
    final: Path  # where the finished file goes, inside data/media
    part: Path  # where the bytes are written until the upload completes
    is_proxy: bool  # an .LRF rather than a clip


@dataclass(frozen=True)
class UploadResult:
    status: str  # added | duplicate | proxy_paired | proxy_held
    message: str
    clip: Clip | None
    clip_ids: list[str]


@dataclass(frozen=True)
class ConfigView:
    clip_id: str
    mount: str
    overlays: dict[str, Any]
    range_start: float | None
    range_end: float | None
    updated_at: str | None
    source: str  # saved | last_used | default


@dataclass(frozen=True)
class ExportArgs:
    source: str
    overlays: dict[str, Any]
    preset: str
    start: float | None
    end: float | None
    mount: str


@dataclass
class _Held:
    path: Path
    timer: threading.Timer


class Workspace:
    def __init__(self, paths: WorkspacePaths, registry: OverlayRegistry) -> None:
        self.paths = paths
        self.registry = registry
        paths.media_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(paths.db_path)
        self.library = Library(self.db)
        self.jobs = Jobs(self.library, paths)
        self._held: dict[str, _Held] = {}
        self._held_lock = threading.Lock()

    def resume(self) -> None:
        """Restart background work that an earlier run did not finish."""
        self.jobs.resume()

    def close(self) -> None:
        with self._held_lock:
            for held in self._held.values():
                held.timer.cancel()
            self._held.clear()
        self.jobs.shutdown()
        self.db.close()

    # Clips

    def clips(self) -> list[Clip]:
        return self.library.all()

    def clip(self, clip_id: str) -> Clip:
        clip = self.library.get(clip_id)
        if clip is None:
            raise NotFound(f"no clip with id {clip_id}")
        return clip

    def is_missing(self, clip: Clip) -> bool:
        return not Path(clip.source_path).exists()

    def remove_clip(self, clip_id: str) -> None:
        """Remove a clip. Uploaded copies and generated files are deleted; referenced originals never are."""
        clip = self.clip(clip_id)
        self.jobs.cancel_proxy(clip.id)
        self.library.delete(clip.id)
        if clip.origin == ORIGIN_UPLOAD and _inside(Path(clip.source_path), self.paths.media_dir):
            Path(clip.source_path).unlink(missing_ok=True)
        if clip.proxy_path and _inside(Path(clip.proxy_path), self.paths.media_dir):
            if not self.library.uses_proxy(clip.proxy_path):
                Path(clip.proxy_path).unlink(missing_ok=True)
        shutil.rmtree(self.paths.clip_cache_dir / clip.id, ignore_errors=True)

    # Import from a folder

    def import_folder(self, folder: str | None) -> ImportResult:
        """Add the MP4 and MOV files of a folder by reference. Relative paths resolve against the project root."""
        _require_tools()
        target = self._folder(folder)
        if not target.is_dir():
            raise BadRequest(f"not a folder: {target}")
        files = sorted(p for p in target.iterdir() if p.is_file())
        lrfs = {p.stem: p for p in files if p.suffix.lower() == ".lrf"}
        added: list[Clip] = []
        existing: list[Clip] = []
        errors: list[dict[str, str]] = []
        for path in files:
            if path.suffix.lower() not in REFERENCE_SUFFIXES:
                continue
            try:
                clip, is_new = self._add_reference(path, lrfs.get(path.stem))
            except (ToolError, ValueError) as exc:
                errors.append({"file": path.name, "error": f"not a readable video file: {exc}"})
                continue
            (added if is_new else existing).append(clip)
        return ImportResult(str(target), added, existing, errors)

    def _folder(self, folder: str | None) -> Path:
        if not folder or not folder.strip():
            return self.paths.videos_dir
        path = Path(folder.strip())
        if not path.is_absolute():
            path = self.paths.project_root / path
        return path.resolve()

    def _add_reference(self, path: Path, lrf: Path | None) -> tuple[Clip, bool]:
        stat = path.stat()
        duplicate = self.library.find_by_name_size(path.name, stat.st_size)
        if duplicate is not None:
            return duplicate, False
        meta = media.probe_metadata(path)
        clip = self._insert(
            name=path.name,
            origin=ORIGIN_REFERENCE,
            source=path.resolve(),
            size=stat.st_size,
            mtime=stat.st_mtime,
            meta=meta,
            lrf=lrf,
        )
        return clip, True

    def _insert(
        self, *, name: str, origin: str, source: Path, size: int, mtime: float, meta: Metadata, lrf: Path | None
    ) -> Clip:
        if lrf is None:
            lrf = self._take_held(Path(name).stem)  # an LRF that arrived before this MP4
        clip = self.library.insert(
            name=name,
            origin=origin,
            source_path=str(source),
            size=size,
            mtime=mtime,
            meta=meta,
            proxy_path=str(lrf) if lrf else None,
            proxy_status=LRF if lrf else PENDING,
        )
        self.jobs.start(clip)
        return clip

    # Upload (the HTTP layer streams the bytes into target.part)

    def begin_upload(self, filename: str) -> UploadTarget:
        if not filename or Path(filename).name != filename or filename in (".", ".."):
            raise BadRequest("invalid file name")
        base = Path(filename)
        if base.suffix.lower() not in UPLOAD_SUFFIXES:
            raise Unsupported(f"{filename}: only MP4, MOV and LRF video files can be uploaded")
        self.paths.media_dir.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            stored = filename if n == 1 else f"{base.stem}_{n}{base.suffix}"
            final = self.paths.media_dir / stored
            part = final.with_name(stored + ".part")
            if not final.exists() and not part.exists():
                try:
                    part.touch(exist_ok=False)  # exclusive, so two uploads never share a part file
                except FileExistsError:
                    pass
                else:
                    return UploadTarget(filename, final, part, base.suffix.lower() == ".lrf")
            n += 1

    def known_duplicate(self, target: UploadTarget, size: int) -> Clip | None:
        if target.is_proxy:
            return None
        return self.library.find_by_name_size(target.name, size)

    def abort_upload(self, target: UploadTarget) -> None:
        target.part.unlink(missing_ok=True)

    def finish_upload(self, target: UploadTarget) -> UploadResult:
        """Probe the written bytes with ffprobe, then move them into place and register the clip."""
        try:
            _require_tools()
            size = target.part.stat().st_size
            duplicate = None if target.is_proxy else self.library.find_by_name_size(target.name, size)
            if duplicate is not None:
                self.abort_upload(target)
                return UploadResult("duplicate", f"{target.name} is already in the library", duplicate, [duplicate.id])
            try:
                meta = media.probe_metadata(target.part)
            except (ToolError, ValueError) as exc:
                raise Invalid(f"{target.name} is not a readable video file", [f"{target.name}: {exc}"]) from exc
            os.replace(target.part, target.final)
            if target.is_proxy:
                return self._attach_uploaded_lrf(target)
            clip = self._insert(
                name=target.name,
                origin=ORIGIN_UPLOAD,
                source=target.final,
                size=size,
                mtime=time.time(),
                meta=meta,
                lrf=None,
            )
            return UploadResult("added", f"{target.name} added to the library", clip, [clip.id])
        except BaseException:
            self.abort_upload(target)
            raise

    def _attach_uploaded_lrf(self, target: UploadTarget) -> UploadResult:
        stem = Path(target.name).stem
        clips = [clip for clip in self.library.named_stem(stem) if clip.proxy_status != LRF]
        if clips:
            for clip in clips:
                self._attach_proxy(clip, target.final)
            ids = [clip.id for clip in clips]
            return UploadResult("proxy_paired", f"{target.name} is the proxy for {len(ids)} clip(s)", None, ids)
        self._hold(stem, target.final)
        return UploadResult("proxy_held", f"{target.name} is held for {HOLD_SECONDS} s, waiting for its MP4", None, [])

    def _attach_proxy(self, clip: Clip, lrf: Path) -> None:
        previous = clip.proxy_path
        self.library.update(clip.id, proxy_path=str(lrf), proxy_status=LRF, proxy_progress=100.0, error=None)
        self.jobs.cancel_proxy(clip.id)
        if previous and previous != str(lrf) and _inside(Path(previous), self.paths.clip_cache_dir):
            Path(previous).unlink(missing_ok=True)  # a generated proxy is no longer needed

    def _hold(self, stem: str, lrf: Path) -> None:
        with self._held_lock:
            previous = self._held.pop(stem, None)
            if previous is not None:
                previous.timer.cancel()
                previous.path.unlink(missing_ok=True)
            timer = threading.Timer(HOLD_SECONDS, self._expire_held, args=(stem, lrf))
            timer.daemon = True
            self._held[stem] = _Held(lrf, timer)
            timer.start()

    def _expire_held(self, stem: str, lrf: Path) -> None:
        with self._held_lock:
            held = self._held.get(stem)
            if held is None or held.path != lrf:
                return
            del self._held[stem]
        lrf.unlink(missing_ok=True)

    def _take_held(self, stem: str) -> Path | None:
        with self._held_lock:
            held = self._held.pop(stem, None)
        if held is None:
            return None
        held.timer.cancel()
        return held.path

    # Overlay configuration

    def config(self, clip_id: str) -> ConfigView:
        self.clip(clip_id)
        return self._effective_config(clip_id)

    def _effective_config(self, clip_id: str) -> ConfigView:
        row = self.library.get_config(clip_id)
        if row is not None:
            return ConfigView(clip_id, row.mount, row.overlays, row.range_start, row.range_end, row.updated_at, "saved")
        last = self.library.last_config()  # a new clip starts from the last saved settings, but never a range
        if last is not None:
            return ConfigView(clip_id, last.mount, last.overlays, None, None, None, "last_used")
        return ConfigView(clip_id, DEFAULT_MOUNT, {}, None, None, None, "default")

    def save_config(
        self,
        clip_id: str,
        *,
        mount: str | None,
        overlays: dict[str, Any] | None,
        range_start: float | None,
        range_end: float | None,
    ) -> ConfigView:
        clip = self.clip(clip_id)
        mount = self._effective_config(clip_id).mount if mount is None else mount
        if mount not in MOUNTS:
            raise Invalid("invalid overlay configuration", [f"mount: {mount!r} is not one of {list(MOUNTS)}"])
        overlays = {} if overlays is None else overlays
        self._validated(overlays)
        try:
            resolve_range(range_start, range_end, clip.meta.duration_s)
        except ExportError as exc:
            raise Invalid("invalid range", [f"range: {exc}"]) from exc
        row = self.library.save_config(
            clip_id, mount=mount, overlays=overlays, range_start=range_start, range_end=range_end
        )
        return ConfigView(clip_id, row.mount, row.overlays, row.range_start, row.range_end, row.updated_at, "saved")

    def _validated(self, overlays: dict[str, Any]) -> dict[str, OverlayConfig]:
        try:
            return validate_config(overlays, self.registry)
        except ConfigError as exc:
            raise Invalid("invalid overlay configuration", exc.errors) from exc

    def overlay_catalog(self, clip_id: str | None) -> dict[str, Any]:
        """The registered overlays with their settings, and whether each one is usable for the clip."""
        clip = self.clip(clip_id) if clip_id else None
        items = []
        for overlay in self.registry.overlays():
            availability = self._availability(overlay, clip) if clip is not None else Availability(True)
            items.append({
                "id": overlay.id,
                "name": overlay.name,
                "description": overlay.description,
                "requires_telemetry": overlay.requires_telemetry,
                "available": availability.available,
                "reason": availability.reason,
                "default_position": overlay.default_position,
                "default_size": overlay.default_size,
                "base_box": list(overlay.base_box),
                "settings": [asdict(setting) for setting in overlay.settings],
            })
        return {
            "clip_id": clip_id,
            "mounts": list(MOUNTS),
            "positions": list(POSITIONS),
            "sizes": list(SIZES),
            "overlays": items,
        }

    def _availability(self, overlay: Overlay, clip: Clip) -> Availability:
        if overlay.requires_telemetry and clip.telemetry_status in (PENDING, RUNNING):
            return Availability(False, "telemetry is still being read")
        if overlay.requires_telemetry and clip.telemetry_status == FAILED:
            return Availability(False, "telemetry could not be read")
        # The registry only checks whether telemetry exists, so a stand-in with no samples is enough here.
        telemetry = Telemetry(samples=Samples.empty(), meta=clip.meta) if clip.meta.telemetry_available else None
        return self.registry.availability(overlay, ClipContext(Path(clip.source_path), clip.meta, telemetry))

    # Preview and export inputs

    def render_overlay(self, clip_id: str, t: float, width: int, guides: bool) -> Image.Image:
        """The overlay layer at time `t` as a transparent RGBA frame `width` px wide, drawn the way export draws it."""
        clip = self.clip(clip_id)
        self._require_source(clip)
        if clip.telemetry_status in (PENDING, RUNNING):
            raise Conflict("telemetry is still being read for this clip, try again shortly")
        view = self._effective_config(clip_id)
        configs = self._validated(view.overlays)
        try:
            ctx = load_clip(clip.source_path, view.mount, cache_root=self.paths.cache_dir)
        except (ToolError, OSError, ValueError) as exc:
            raise Conflict(f"the source clip could not be read: {clip.name}: {exc}") from exc
        meta = ctx.meta
        try:
            rng = resolve_range(view.range_start, view.range_end, meta.duration_s)
        except ExportError as exc:
            raise Invalid("invalid range", [f"range: {exc}"]) from exc
        t = min(max(float(t), 0.0), meta.duration_s)

        usable = {
            oid: cfg for oid, cfg in configs.items()
            if cfg.enabled and self.registry.availability(cfg.overlay, ctx).available
        }
        canvas = Image.new("RGBA", (width, round(width * meta.display_height / meta.display_width)), (0, 0, 0, 0))
        if usable:
            try:
                items = plan_layer(usable, ctx, rng, meta.display_width, meta.display_height)
            except ValueError as exc:
                raise Invalid("the overlays do not fit this frame", [str(exc)]) from exc
            layer = render_layer(items, t)
            scale = width / meta.display_width
            small = layer.resize(
                (max(1, round(layer.width * scale)), max(1, round(layer.height * scale))),
                Image.Resampling.LANCZOS,
            )
            ux0, uy0, _, _ = union_box(items)
            canvas.alpha_composite(small, dest=(round(ux0 * scale), round(uy0 * scale)))
        if guides:
            draw_safe_guides(canvas)
        return canvas

    def export_args(self, clip_id: str, preset: str) -> ExportArgs:
        """Check that a clip can be exported with its saved configuration and return the engine's inputs."""
        clip = self.clip(clip_id)
        if preset not in PRESETS:
            raise Invalid(f"invalid preset {preset!r}", [f"preset: {preset!r} is not one of {list(PRESETS)}"])
        self._require_source(clip)
        view = self._effective_config(clip_id)
        enabled = [cfg for cfg in self._validated(view.overlays).values() if cfg.enabled]
        if not enabled:
            raise Invalid("no overlay is enabled, so there is nothing to export", ["overlays: none is enabled"])
        for cfg in enabled:
            availability = self._availability(cfg.overlay, clip)
            if not availability.available:
                raise Invalid(
                    f"overlay {cfg.overlay.id!r} is unavailable for this clip: {availability.reason}",
                    [f"{cfg.overlay.id}: {availability.reason}"],
                )
        try:
            resolve_range(view.range_start, view.range_end, clip.meta.duration_s)
        except ExportError as exc:
            raise Invalid("invalid range", [f"range: {exc}"]) from exc
        return ExportArgs(
            source=clip.source_path,
            overlays=view.overlays,
            preset=preset,
            start=view.range_start,
            end=view.range_end,
            mount=view.mount,
        )

    def clip_ids_by_source(self) -> dict[str, str]:
        return {clip.source_path: clip.id for clip in self.library.all()}

    def _require_source(self, clip: Clip) -> None:
        if self.is_missing(clip):
            raise Conflict(
                f"{clip.name} is missing: its file was moved or deleted",
                [f"{clip.name}: source file not found at {clip.source_path}"],
            )


def _require_tools() -> None:
    try:
        require_ffmpeg()
    except MissingToolError as exc:
        raise Unavailable(str(exc)) from exc


def _inside(path: Path, folder: Path) -> bool:
    return path.resolve().is_relative_to(folder.resolve())

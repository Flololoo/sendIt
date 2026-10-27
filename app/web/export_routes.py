"""Export routes: start an export from a clip's saved settings, list and cancel jobs, and serve finished files."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse

from app.render.queue import ExportQueue
from app.workspace import Workspace
from app.workspace.errors import Conflict, NotFound

from .library_routes import get_workspace
from .schemas import ExportIn
from .views import job_json

router = APIRouter()


def get_queue(request: Request) -> ExportQueue:
    return request.app.state.queue


def _clip_ids(ws: Workspace) -> dict[str, str]:
    return ws.clip_ids_by_source()


@router.post("/api/clips/{clip_id}/export", status_code=202)
def start_export(
    clip_id: str,
    body: ExportIn | None = None,
    ws: Workspace = Depends(get_workspace),
    queue: ExportQueue = Depends(get_queue),
) -> dict:
    args = ws.export_args(clip_id, body.preset if body else "original")
    job_id = queue.submit(
        args.source, args.overlays, preset=args.preset, start=args.start, end=args.end, mount=args.mount
    )
    return job_json(queue.get(job_id), clip_id)


@router.get("/api/jobs")
def list_jobs(ws: Workspace = Depends(get_workspace), queue: ExportQueue = Depends(get_queue)) -> list[dict]:
    clip_ids = _clip_ids(ws)
    return [job_json(job, clip_ids.get(job.clip)) for job in queue.jobs()]


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str, ws: Workspace = Depends(get_workspace), queue: ExportQueue = Depends(get_queue)) -> dict:
    try:
        job = queue.get(job_id)
    except KeyError as exc:
        raise NotFound(f"no job with id {job_id}") from exc
    return job_json(job, _clip_ids(ws).get(job.clip))


@router.post("/api/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str, ws: Workspace = Depends(get_workspace), queue: ExportQueue = Depends(get_queue)
) -> dict:
    try:
        cancelled = queue.cancel(job_id)
    except KeyError as exc:
        raise NotFound(f"no job with id {job_id}") from exc
    if not cancelled:
        raise Conflict("the job has already finished")
    job = queue.get(job_id)
    return job_json(job, _clip_ids(ws).get(job.clip))


@router.get("/api/exports/{name}")
def get_export(name: str, request: Request, download: bool = False) -> FileResponse:
    """A finished export. Plays inline by default; `?download=1` sends it as an attachment."""
    exports_dir: Path = request.app.state.paths.exports_dir
    if Path(name).name != name:
        raise NotFound("invalid export name")
    path = exports_dir / name
    if not path.is_file():
        raise NotFound(f"no export named {name}")
    return FileResponse(path, media_type="video/mp4", filename=name if download else None)

"""Library routes: folder import, streamed uploads, the clip list, removal, and each clip's thumbnail and proxy."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.requests import ClientDisconnect

from app.workspace import Workspace, UploadResult
from app.workspace.errors import BadRequest, Conflict, NotFound
from app.workspace.jobs import THUMBNAIL_NAME
from app.workspace.library import DONE, LRF

from .schemas import ImportIn
from .views import clip_json

router = APIRouter()

WRITE_BLOCK = 8 << 20  # bytes collected before one write to disk, so a 13 GB upload makes ~1600 writes


def get_workspace(request: Request) -> Workspace:
    return request.app.state.workspace


@router.get("/api/workspace")
def workspace_info(request: Request) -> dict:
    paths = request.app.state.paths
    return {
        "data_dir": str(paths.data_dir),
        "exports_dir": str(paths.exports_dir),
        "default_import_folder": str(paths.videos_dir),
    }


@router.get("/api/clips")
def list_clips(ws: Workspace = Depends(get_workspace)) -> list[dict]:
    return [clip_json(clip, ws.is_missing(clip)) for clip in ws.clips()]


@router.get("/api/clips/{clip_id}")
def get_clip(clip_id: str, ws: Workspace = Depends(get_workspace)) -> dict:
    clip = ws.clip(clip_id)
    return clip_json(clip, ws.is_missing(clip))


@router.post("/api/import-folder")
def import_folder(body: ImportIn | None = None, ws: Workspace = Depends(get_workspace)) -> dict:
    result = ws.import_folder(body.path if body else None)
    return {
        "folder": result.folder,
        "added": [clip_json(clip, ws.is_missing(clip)) for clip in result.added],
        "existing": [clip_json(clip, ws.is_missing(clip)) for clip in result.existing],
        "errors": result.errors,
    }


@router.put("/api/uploads/{filename}")
async def upload(filename: str, request: Request, ws: Workspace = Depends(get_workspace)) -> JSONResponse:
    """Stream the request body into data/media/<name>.part, then probe and register it.

    The body is never held in memory. An interrupted upload leaves no file behind.
    """
    target = ws.begin_upload(filename)
    declared = _declared_length(request)
    try:
        if declared is not None:
            duplicate = ws.known_duplicate(target, declared)
            if duplicate is not None:
                ws.abort_upload(target)  # reject before reading a body we already have
                return _upload_response(ws, UploadResult(
                    "duplicate", f"{filename} is already in the library", duplicate, [duplicate.id]
                ), 200)
        received = await _write_body(request, target.part)
        if declared is not None and received != declared:
            raise BadRequest(f"{filename}: the upload ended after {received} of {declared} bytes")
        result = await run_in_threadpool(ws.finish_upload, target)
    except ClientDisconnect:
        ws.abort_upload(target)
        return JSONResponse({"detail": f"{filename}: the upload was interrupted, nothing was added"}, status_code=400)
    except BaseException:
        ws.abort_upload(target)
        raise
    return _upload_response(ws, result, 201 if result.status == "added" else 200)


@router.delete("/api/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: str, ws: Workspace = Depends(get_workspace)) -> Response:
    ws.remove_clip(clip_id)
    return Response(status_code=204)


@router.get("/api/clips/{clip_id}/thumbnail")
def thumbnail(clip_id: str, ws: Workspace = Depends(get_workspace)) -> FileResponse:
    clip = ws.clip(clip_id)
    path = ws.paths.clip_cache_dir / clip.id / THUMBNAIL_NAME
    if clip.thumbnail_status != DONE or not path.exists():
        raise NotFound("no thumbnail for this clip yet")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/api/clips/{clip_id}/proxy")
def proxy(clip_id: str, ws: Workspace = Depends(get_workspace)) -> FileResponse:
    clip = ws.clip(clip_id)
    if ws.is_missing(clip):
        raise Conflict(f"{clip.name} is missing: its file was moved or deleted")
    if clip.proxy_status not in (DONE, LRF) or not clip.proxy_path or not Path(clip.proxy_path).exists():
        raise NotFound("no playable proxy for this clip yet")
    return FileResponse(clip.proxy_path, media_type="video/mp4")


def _declared_length(request: Request) -> int | None:
    value = request.headers.get("content-length")
    return int(value) if value is not None and value.isdigit() else None


async def _write_body(request: Request, part: Path) -> int:
    received = 0
    buffer = bytearray()
    with open(part, "wb") as handle:
        async for chunk in request.stream():
            buffer += chunk
            received += len(chunk)
            if len(buffer) >= WRITE_BLOCK:
                await run_in_threadpool(handle.write, bytes(buffer))
                buffer.clear()
        if buffer:
            await run_in_threadpool(handle.write, bytes(buffer))
    return received


def _upload_response(ws: Workspace, result: UploadResult, status: int) -> JSONResponse:
    clip = None
    if result.clip is not None:
        clip = clip_json(result.clip, ws.is_missing(result.clip))
    return JSONResponse(
        {"status": result.status, "message": result.message, "clip": clip, "clip_ids": result.clip_ids},
        status_code=status,
    )

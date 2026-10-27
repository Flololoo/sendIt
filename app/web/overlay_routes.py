"""Overlay routes: the registry with availability, each clip's saved configuration, and the overlay layer as PNG."""

from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from app.render.preview import PREVIEW_WIDTH
from app.workspace import Workspace

from .library_routes import get_workspace
from .schemas import ConfigIn
from .views import config_json

router = APIRouter()


@router.get("/api/overlays")
def overlays(clip: str | None = None, ws: Workspace = Depends(get_workspace)) -> dict:
    return ws.overlay_catalog(clip)


@router.get("/api/clips/{clip_id}/config")
def get_config(clip_id: str, request: Request, ws: Workspace = Depends(get_workspace)) -> dict:
    return config_json(ws.config(clip_id), request.app.state.registry)


@router.put("/api/clips/{clip_id}/config")
def put_config(
    clip_id: str, body: ConfigIn, request: Request, ws: Workspace = Depends(get_workspace)
) -> dict:
    view = ws.save_config(
        clip_id,
        mount=body.mount,
        overlays=body.overlays,
        range_start=body.range.start if body.range else None,
        range_end=body.range.end if body.range else None,
    )
    return config_json(view, request.app.state.registry)


@router.get("/api/clips/{clip_id}/overlay.png")
def overlay_png(
    clip_id: str,
    t: float = Query(0.0, ge=0, allow_inf_nan=False),
    w: int = Query(PREVIEW_WIDTH, ge=16, le=3840),
    guides: bool = False,
    ws: Workspace = Depends(get_workspace),
) -> Response:
    """The transparent overlay layer at time t (seconds), `w` px wide. Guides are drawn only when asked."""
    image = ws.render_overlay(clip_id, t, w, guides)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

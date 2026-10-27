"""App factory: wires the workspace, the export queue, the HTTP routes and the static frontend together."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.overlays.registry import OverlayRegistry, default_registry
from app.render.queue import ExportQueue
from app.workspace import Workspace, WorkspaceError, WorkspacePaths

from . import export_routes, library_routes, overlay_routes

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.workspace.resume()
    try:
        yield
    finally:
        app.state.queue.close()
        app.state.workspace.close()


async def _workspace_error(request: Request, exc: WorkspaceError) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "errors": exc.errors}, status_code=exc.status_code)


def create_app(paths: WorkspacePaths | None = None, *, registry: OverlayRegistry = default_registry) -> FastAPI:
    """Build the app. Tests pass paths under a temporary folder and a registry with a test overlay."""
    paths = paths or WorkspacePaths.default()
    app = FastAPI(title="send.it.slowly workspace", version="0.1.0", lifespan=_lifespan)
    app.state.paths = paths
    app.state.registry = registry
    app.state.workspace = Workspace(paths, registry)
    app.state.queue = ExportQueue(
        registry=registry,
        jobs_path=paths.jobs_path,
        exports_dir=paths.exports_dir,
        cache_root=paths.cache_dir,
    )
    app.add_exception_handler(WorkspaceError, _workspace_error)
    for router in (library_routes.router, overlay_routes.router, export_routes.router):
        app.include_router(router)
    # Last, so API routes always win over static file names.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
    return app

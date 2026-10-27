"""Web layer: the FastAPI app that serves the workspace API and the static frontend."""

from .app import create_app

__all__ = ["create_app"]

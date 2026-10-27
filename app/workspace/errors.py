"""Errors the workspace raises. The web layer turns each one into an HTTP response with its status code."""

from __future__ import annotations


class WorkspaceError(Exception):
    status_code = 500

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors = errors or [message]


class BadRequest(WorkspaceError):
    status_code = 400


class NotFound(WorkspaceError):
    status_code = 404


class Conflict(WorkspaceError):
    status_code = 409


class Unsupported(WorkspaceError):
    status_code = 415


class Invalid(WorkspaceError):
    """The request is well formed but its content is not acceptable, such as a bad setting or an unreadable video."""

    status_code = 422


class Unavailable(WorkspaceError):
    status_code = 503

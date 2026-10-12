"""Structured error types returned by every MCP tool.

Raw exceptions never escape the tool handlers.  Instead services raise (and
handlers catch) subclasses of ``CoachError`` and translate them into the
structured ``error`` payload a language model can reason about.
"""

from __future__ import annotations

from typing import Any, Optional


class CoachError(Exception):
    """Base class for all coach-domain errors."""

    code: str = "coach_error"
    retryable: bool = False
    http_status: Optional[int] = None

    def __init__(self, message: str, *, code: Optional[str] = None,
                 details: Optional[dict[str, Any]] = None,
                 retryable: Optional[bool] = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}
        if retryable is not None:
            self.retryable = retryable

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "details": self.details,
            }
        }


class ConfigError(CoachError):
    """Missing/invalid environment configuration (e.g. database path)."""

    code = "config_error"


class NotFoundError(CoachError):
    """A requested entity (problem, profile) does not exist."""

    code = "not_found"


class DataAccessError(CoachError):
    """A database query failed; carries the underlying status."""

    code = "data_access_error"

    def __init__(self, message: str, *, http_status: Optional[int] = None, **kw: Any):
        self.http_status = http_status
        super().__init__(message, **kw)


class RateLimitError(CoachError):
    """We were rate limited (user-facing retryable error)."""

    code = "rate_limit"
    retryable = True


class BadRequestError(CoachError):
    """The tool input was structurally valid but semantically invalid."""

    code = "bad_request"
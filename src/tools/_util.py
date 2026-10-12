"""Shared helpers for thin tool handlers."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.errors import CoachError


def error_payload(exc: Exception) -> dict[str, Any]:
    """Translate any exception into a structured, LLM-readable error dict."""
    if isinstance(exc, CoachError):
        return exc.to_dict()
    if isinstance(exc, ValidationError):
        return {
            "error": {
                "code": "invalid_input",
                "message": "One or more inputs failed validation.",
                "retryable": False,
                "details": exc.errors(),
            }
        }
    return {
        "error": {
            "code": "internal_error",
            "message": f"Unexpected error: {exc}",
            "retryable": False,
            "details": {"type": type(exc).__name__},
        }
    }
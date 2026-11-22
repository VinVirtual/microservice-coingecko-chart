"""Error type and the JSON envelope every response body uses."""

from __future__ import annotations

from typing import Any, Dict, Optional


class ApiError(Exception):
    """An error with an HTTP status, a stable machine code and a safe message."""

    def __init__(self, status: int, code: str, message: str,
                 details: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def envelope(data: Any = None, *, error: Optional[ApiError] = None,
             meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {
        "success": error is None,
        "data": data if error is None else None,
        "error": None if error is None else {
            "code": error.code, "message": error.message, "details": error.details,
        },
        "meta": meta or {},
    }

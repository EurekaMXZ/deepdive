from __future__ import annotations

from typing import Any


TERMINAL_ANALYSIS_STATUSES = frozenset({"completed", "failed", "cancelled"})
TERMINAL_STREAM_EVENT_TYPES = frozenset({"done", "analysis_error", "error"})


def status_event_payload(*, status: str) -> dict[str, str]:
    return {"status": status}


def error_event_payload(*, code: str, message: str, retryable: bool | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if retryable is not None:
        error["retryable"] = retryable
    return {"error": error}


from __future__ import annotations

import base64
from datetime import datetime
from uuid import UUID

from backend.api.records import AnalysisRecord


def encode_list_cursor(record: AnalysisRecord) -> str:
    raw = f"{record.created_at.isoformat()}|{record.analysis_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_list_cursor(value: str | None) -> tuple[datetime, UUID] | None:
    if not value:
        return None
    try:
        decoded = _decode_cursor_text(value)
    except (ValueError, UnicodeDecodeError):
        return None
    if "|" not in decoded:
        return None
    created_at_text, id_text = decoded.split("|", 1)
    try:
        return datetime.fromisoformat(created_at_text), UUID(id_text)
    except ValueError:
        return None


def cursor_offset(value: str | None) -> int:
    if value is None or not str(value).strip():
        return 0
    if str(value).isdigit():
        return int(str(value))
    return 0


def _decode_cursor_text(value: str) -> str:
    if "|" in value:
        return value
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode()).decode()

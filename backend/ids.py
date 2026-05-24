from __future__ import annotations

import uuid


def new_uuid7() -> uuid.UUID:
    """Return a platform UUIDv7 value."""
    return uuid.uuid7()

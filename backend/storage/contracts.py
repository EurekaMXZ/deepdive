from __future__ import annotations

from typing import Protocol
from pathlib import Path


class ObjectStorage(Protocol):
    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        ...

    def get_bytes(self, key: str) -> bytes:
        ...

    def put_file(self, key: str, path: Path, *, content_type: str = "application/octet-stream") -> None:
        ...

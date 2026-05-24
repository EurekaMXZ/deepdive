from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class InMemoryObjectStorage:
    objects: dict[str, bytes] = field(default_factory=dict[str, bytes])
    content_types: dict[str, str] = field(default_factory=dict[str, str])

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        self.objects[key] = data
        self.content_types[key] = content_type

    def get_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def put_file(self, key: str, path: Path, *, content_type: str = "application/octet-stream") -> None:
        self.put_bytes(key, path.read_bytes(), content_type=content_type)

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConsumedKafkaMessage:
    topic: str
    key: bytes | None
    value: bytes
    partition: int | None = None
    offset: int | None = None

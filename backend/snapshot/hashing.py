from __future__ import annotations

import hashlib


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode())


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()

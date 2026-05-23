from __future__ import annotations

from backend.storage.contracts import ObjectStorage
from backend.storage.keys import (
    blob_key,
    evidence_key,
    file_tree_key,
    git_bundle_key,
    instruction_key,
    manifest_key,
    tool_result_key,
    tree_text_key,
)
from backend.storage.memory import InMemoryObjectStorage
from backend.storage.minio import MinioObjectStorage

DEFAULT_OBJECT_BUCKET = "deepdive-objects"

__all__ = [
    "DEFAULT_OBJECT_BUCKET",
    "InMemoryObjectStorage",
    "MinioObjectStorage",
    "ObjectStorage",
    "blob_key",
    "evidence_key",
    "file_tree_key",
    "git_bundle_key",
    "instruction_key",
    "manifest_key",
    "tool_result_key",
    "tree_text_key",
]

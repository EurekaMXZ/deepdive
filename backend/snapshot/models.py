from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Protocol
from uuid import UUID

from backend.config import SnapshotConfig
from backend.security import SECRET_PATH_POLICY_VERSION
from backend.snapshot.hashing import sha256_bytes
from backend.storage import ObjectStorage


@dataclass(frozen=True)
class SnapshotPolicy:
    max_file_bytes: int
    max_git_bundle_bytes: int = 536_870_912
    lfs_policy: str = "pointer_only"
    submodule_policy: str = "record_only"
    binary_policy: str = "metadata_only"
    secret_path_policy_version: str = SECRET_PATH_POLICY_VERSION

    @classmethod
    def from_config(cls, config: SnapshotConfig) -> SnapshotPolicy:
        return cls(
            max_file_bytes=config.max_file_bytes,
            max_git_bundle_bytes=config.max_git_bundle_bytes,
            lfs_policy=config.lfs_policy,
            submodule_policy=config.submodule_policy,
            binary_policy=config.binary_policy,
            secret_path_policy_version=SECRET_PATH_POLICY_VERSION,
        )

    @property
    def hash(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        return sha256_bytes(encoded)


@dataclass(frozen=True)
class SnapshotBuildRequest:
    snapshot_id: UUID
    repository_url: str
    requested_ref: str
    policy: SnapshotPolicy
    storage: ObjectStorage
    timeout_seconds: int = 300


@dataclass(frozen=True)
class SnapshotFileRecord:
    path: str
    path_hash: str
    parent_path: str | None
    name: str
    entry_kind: str
    git_mode: str | None
    git_blob_oid: str | None
    content_key: str | None
    content_hash: str | None
    size_bytes: int | None
    line_count: int | None
    is_binary: bool
    is_large: bool


@dataclass(frozen=True)
class SnapshotInstructionRecord:
    path: str
    scope_path: str
    depth: int
    content_hash: str
    content_ref: str


@dataclass(frozen=True)
class SnapshotBuildResult:
    snapshot_id: UUID
    repository_url_hash: str
    requested_ref: str
    resolved_commit_sha: str
    tree_sha: str
    snapshot_policy_hash: str
    manifest_key: str
    git_bundle_key: str | None
    tree_text_key: str
    file_tree_key: str
    file_count: int
    total_bytes: int
    files: list[SnapshotFileRecord]
    instructions: list[SnapshotInstructionRecord]


class SnapshotBuilder(Protocol):
    def build(self, request: SnapshotBuildRequest) -> SnapshotBuildResult: ...


class SnapshotBuildError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

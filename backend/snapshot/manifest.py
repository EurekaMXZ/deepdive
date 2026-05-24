from __future__ import annotations

import json
from compression import zstd
from dataclasses import asdict
from datetime import UTC, datetime

from backend.snapshot.models import SnapshotBuildResult, SnapshotFileRecord, SnapshotInstructionRecord, SnapshotPolicy


def tree_text(files: list[SnapshotFileRecord]) -> str:
    return "".join(f"{entry.path}\n" for entry in files)


def file_tree_json(files: list[SnapshotFileRecord]) -> dict[str, object]:
    return {
        "files": [
            {
                "path": entry.path,
                "kind": entry.entry_kind,
                "size_bytes": entry.size_bytes,
                "is_binary": entry.is_binary,
                "is_large": entry.is_large,
            }
            for entry in files
        ]
    }


def manifest_json(
    *,
    result: SnapshotBuildResult,
    policy: SnapshotPolicy,
    instructions: list[SnapshotInstructionRecord],
) -> dict[str, object]:
    return {
        "snapshot_id": str(result.snapshot_id),
        "repository_url_hash": result.repository_url_hash,
        "requested_ref": result.requested_ref,
        "resolved_commit_sha": result.resolved_commit_sha,
        "tree_sha": result.tree_sha,
        "snapshot_policy_hash": result.snapshot_policy_hash,
        "created_at": datetime.now(UTC).isoformat(),
        "file_count": result.file_count,
        "total_bytes": result.total_bytes,
        "objects": {
            "tree_text_key": result.tree_text_key,
            "file_tree_key": result.file_tree_key,
            "git_bundle_key": result.git_bundle_key,
        },
        "files": [asdict(entry) for entry in result.files],
        "instructions": [asdict(entry) for entry in instructions],
        "policy": asdict(policy),
    }


def zstd_json_bytes(value: object) -> bytes:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return zstd.compress(encoded)

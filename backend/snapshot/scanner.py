from __future__ import annotations

from pathlib import Path, PurePosixPath
from collections.abc import Callable

from backend.snapshot.git_cli import GitTreeEntry
from backend.snapshot.hashing import sha256_bytes, sha256_text
from backend.snapshot.models import SnapshotFileRecord, SnapshotInstructionRecord, SnapshotPolicy
from backend.security import is_secret_path
from backend.storage import ObjectStorage, blob_key, instruction_key


class SnapshotScanner:
    def scan(
        self,
        *,
        snapshot_id,
        checkout_dir: Path | None = None,
        tree_entries: list[GitTreeEntry],
        policy: SnapshotPolicy,
        storage: ObjectStorage,
        blob_reader: Callable[[GitTreeEntry], bytes] | None = None,
    ) -> tuple[list[SnapshotFileRecord], list[SnapshotInstructionRecord]]:
        records: dict[str, SnapshotFileRecord] = {}
        instructions: list[SnapshotInstructionRecord] = []

        for tree_entry in sorted(tree_entries, key=lambda entry: entry.path):
            path = _normalize_path(tree_entry.path)
            _ensure_directory_records(records, path)
            fs_path = checkout_dir / Path(path) if checkout_dir is not None else None
            if tree_entry.kind != "blob":
                records[path] = _metadata_record(path, tree_entry, entry_kind=tree_entry.kind)
                continue
            if blob_reader is None and (fs_path is None or not fs_path.exists() or not fs_path.is_file()):
                records[path] = _metadata_record(path, tree_entry, entry_kind="file")
                continue
            if is_secret_path(path):
                records[path] = _secret_file_record(path, tree_entry)
                continue
            if tree_entry.size is not None and tree_entry.size > policy.max_file_bytes:
                records[path] = _large_file_record(path, tree_entry)
                continue

            content = blob_reader(tree_entry) if blob_reader is not None else fs_path.read_bytes()
            is_binary = _is_binary(content)
            is_large = len(content) > policy.max_file_bytes
            content_hash = sha256_bytes(content)
            content_key = None
            line_count = None
            if not is_binary and not is_large:
                content_key = blob_key(content_hash)
                storage.put_bytes(content_key, content, content_type="text/plain; charset=utf-8")
                line_count = _line_count(content)

            records[path] = SnapshotFileRecord(
                path=path,
                path_hash=sha256_text(path),
                parent_path=_parent_path(path),
                name=PurePosixPath(path).name,
                entry_kind="file",
                git_mode=tree_entry.mode,
                git_blob_oid=tree_entry.oid,
                content_key=content_key,
                content_hash=content_hash,
                size_bytes=len(content),
                line_count=line_count,
                is_binary=is_binary,
                is_large=is_large,
            )

            if PurePosixPath(path).name == "AGENTS.md" and not is_binary and not is_large:
                path_hash = sha256_text(path)
                key = instruction_key(snapshot_id, path_hash)
                storage.put_bytes(key, content, content_type="text/markdown; charset=utf-8")
                scope_path = _parent_path(path) or ""
                instructions.append(
                    SnapshotInstructionRecord(
                        path=path,
                        scope_path=scope_path,
                        depth=_path_depth(scope_path),
                        content_hash=content_hash,
                        content_ref=key,
                    )
                )

        return list(records.values()), instructions


def _ensure_directory_records(records: dict[str, SnapshotFileRecord], path: str) -> None:
    current = PurePosixPath()
    for part in PurePosixPath(path).parts[:-1]:
        current = current / part
        current_path = current.as_posix()
        if current_path in records:
            continue
        records[current_path] = SnapshotFileRecord(
            path=current_path,
            path_hash=sha256_text(current_path),
            parent_path=_parent_path(current_path),
            name=PurePosixPath(current_path).name,
            entry_kind="directory",
            git_mode=None,
            git_blob_oid=None,
            content_key=None,
            content_hash=None,
            size_bytes=None,
            line_count=None,
            is_binary=False,
            is_large=False,
        )


def _metadata_record(path: str, tree_entry: GitTreeEntry, *, entry_kind: str) -> SnapshotFileRecord:
    return SnapshotFileRecord(
        path=path,
        path_hash=sha256_text(path),
        parent_path=_parent_path(path),
        name=PurePosixPath(path).name,
        entry_kind=entry_kind,
        git_mode=tree_entry.mode,
        git_blob_oid=tree_entry.oid,
        content_key=None,
        content_hash=None,
        size_bytes=tree_entry.size,
        line_count=None,
        is_binary=False,
        is_large=False,
    )


def _large_file_record(path: str, tree_entry: GitTreeEntry) -> SnapshotFileRecord:
    return SnapshotFileRecord(
        path=path,
        path_hash=sha256_text(path),
        parent_path=_parent_path(path),
        name=PurePosixPath(path).name,
        entry_kind="file",
        git_mode=tree_entry.mode,
        git_blob_oid=tree_entry.oid,
        content_key=None,
        content_hash=None,
        size_bytes=tree_entry.size,
        line_count=None,
        is_binary=False,
        is_large=True,
    )


def _secret_file_record(path: str, tree_entry: GitTreeEntry) -> SnapshotFileRecord:
    return SnapshotFileRecord(
        path=path,
        path_hash=sha256_text(path),
        parent_path=_parent_path(path),
        name=PurePosixPath(path).name,
        entry_kind="file",
        git_mode=tree_entry.mode,
        git_blob_oid=tree_entry.oid,
        content_key=None,
        content_hash=None,
        size_bytes=tree_entry.size,
        line_count=None,
        is_binary=False,
        is_large=True,
    )


def _normalize_path(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def _parent_path(path: str) -> str | None:
    parent = PurePosixPath(path).parent.as_posix()
    return None if parent == "." else parent


def _path_depth(path: str) -> int:
    return 0 if path == "" else len(PurePosixPath(path).parts)


def _is_binary(content: bytes) -> bool:
    return b"\0" in content


def _line_count(content: bytes) -> int:
    if not content:
        return 0
    newline_count = content.count(b"\n")
    return newline_count if content.endswith(b"\n") else newline_count + 1


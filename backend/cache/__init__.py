from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class CacheCoverage:
    prefix: str
    file_count: int
    bytes: int


class LocalSourceCache:
    def __init__(self, *, root_dir: Path | str) -> None:
        self._root_dir = Path(root_dir)

    def snapshot_root(self, snapshot_id: UUID) -> Path:
        return self._root_dir / "snapshots" / str(snapshot_id)

    def files_root(self, snapshot_id: UUID) -> Path:
        return self.snapshot_root(snapshot_id) / "files"

    def file_path(self, snapshot_id: UUID, path: str) -> Path:
        safe_path = normalize_repo_path(path)
        root = self.files_root(snapshot_id)
        target = root / Path(*safe_path.split("/"))
        _ensure_within_root(root, target)
        return target

    def is_prefix_covered(self, snapshot_id: UUID, prefix: str) -> bool:
        target = normalize_prefix(prefix)
        for entry in self._read_coverage(snapshot_id).get("prefixes", []):
            covered = normalize_prefix(entry.get("prefix", ""))
            if target == covered or target.startswith(covered):
                return True
        return False

    def mark_prefix_covered(self, snapshot_id: UUID, *, prefix: str, file_count: int, bytes_written: int) -> None:
        coverage = self._read_coverage(snapshot_id)
        prefixes = coverage.setdefault("prefixes", [])
        normalized_prefix = normalize_prefix(prefix)
        prefixes.append(
            {
                "prefix": normalized_prefix,
                "completed_at": datetime.now(UTC).isoformat(),
                "file_count": file_count,
                "bytes": bytes_written,
            }
        )
        coverage["snapshot_id"] = str(snapshot_id)
        self._write_coverage(snapshot_id, coverage)

    def prefix_lock(self, snapshot_id: UUID, prefix: str):
        lock_name = normalize_prefix(prefix).replace("/", "__") or "root"
        lock_path = self.snapshot_root(snapshot_id) / "locks" / f"{lock_name}.lock"
        return FileLock(lock_path)

    def write_file(self, snapshot_id: UUID, path: str, data: bytes) -> Path:
        target = self.file_path(snapshot_id, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target

    def cleanup(self, config) -> dict[str, int]:
        snapshots_root = self._root_dir / "snapshots"
        if not snapshots_root.is_dir():
            return {"removed_snapshots": 0, "removed_bytes": 0}

        removed_snapshots = 0
        removed_bytes = 0
        cutoff = datetime.now(UTC) - timedelta(days=max(0, int(config.ttl_days)))
        snapshot_dirs = [path for path in snapshots_root.iterdir() if path.is_dir()]
        for path in list(snapshot_dirs):
            last_modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if last_modified >= cutoff:
                continue
            removed_bytes += _directory_size(path)
            shutil.rmtree(path, ignore_errors=True)
            removed_snapshots += 1
            snapshot_dirs.remove(path)

        total_bytes = sum(_directory_size(path) for path in snapshot_dirs if path.exists())
        max_bytes = int(config.max_worker_cache_bytes)
        if max_bytes > 0 and total_bytes > max_bytes:
            for path in sorted((path for path in snapshot_dirs if path.exists()), key=_oldest_mtime):
                if total_bytes <= max_bytes:
                    break
                size = _directory_size(path)
                shutil.rmtree(path, ignore_errors=True)
                removed_snapshots += 1
                removed_bytes += size
                total_bytes -= size

        min_free_percent = int(getattr(config, "min_free_disk_percent", 0) or 0)
        if min_free_percent > 0:
            for path in sorted((path for path in snapshot_dirs if path.exists()), key=_oldest_mtime):
                if _free_disk_percent(self._root_dir) >= min_free_percent:
                    break
                size = _directory_size(path)
                shutil.rmtree(path, ignore_errors=True)
                removed_snapshots += 1
                removed_bytes += size

        return {"removed_snapshots": removed_snapshots, "removed_bytes": removed_bytes}

    def _coverage_path(self, snapshot_id: UUID) -> Path:
        return self.snapshot_root(snapshot_id) / "coverage.json"

    def _read_coverage(self, snapshot_id: UUID) -> dict:
        path = self._coverage_path(snapshot_id)
        if not path.is_file():
            return {"snapshot_id": str(snapshot_id), "prefixes": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_coverage(self, snapshot_id: UUID, coverage: dict) -> None:
        path = self._coverage_path(snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(coverage, sort_keys=True), encoding="utf-8")
        tmp.replace(path)


class FileLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def __enter__(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+b")
        _lock_file(handle)
        self._handle = handle
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            _unlock_file(handle)
        finally:
            handle.close()


if os.name == "nt":
    import msvcrt

    def _lock_file(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock_file(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock_file(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock_file(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def normalize_repo_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(_is_unsafe_repo_path_part(part) for part in parts):
        raise ValueError("unsafe repository path")
    return "/".join(parts)


def normalize_prefix(prefix: str | None) -> str:
    if not prefix:
        return ""
    normalized = prefix.replace("\\", "/").strip("/")
    if not normalized:
        return ""
    parts = [part for part in normalized.split("/") if part and part != "."]
    if any(_is_unsafe_repo_path_part(part) for part in parts):
        raise ValueError("unsafe repository prefix")
    return "/".join(parts) + "/"


def _is_unsafe_repo_path_part(part: str) -> bool:
    reserved_devices = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    device_name = part.split(".", 1)[0].lower()
    return (
        part == ".."
        or ":" in part
        or part.startswith("//")
        or device_name in reserved_devices
    )


def _ensure_within_root(root: Path, target: Path) -> None:
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("unsafe repository path") from exc


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _oldest_mtime(path: Path) -> float:
    oldest = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            oldest = min(oldest, child.stat().st_mtime)
        except FileNotFoundError:
            continue
    return oldest


def _free_disk_percent(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    total, _, free = shutil.disk_usage(path)
    if total <= 0:
        return 100.0
    return (free / total) * 100

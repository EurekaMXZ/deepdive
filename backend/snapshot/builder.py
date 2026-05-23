from __future__ import annotations

from pathlib import Path
import tempfile

from backend.snapshot.git_cli import GitCommandRunner
from backend.snapshot.hashing import sha256_text
from backend.snapshot.manifest import file_tree_json, manifest_json, tree_text, zstd_json_bytes
from backend.snapshot.models import SnapshotBuildError, SnapshotBuildRequest, SnapshotBuildResult
from backend.snapshot.scanner import SnapshotScanner
from backend.storage import file_tree_key, git_bundle_key, manifest_key, tree_text_key


class GitSnapshotBuilder:
    def __init__(
        self,
        *,
        git: GitCommandRunner | None = None,
        scanner: SnapshotScanner | None = None,
    ) -> None:
        self._git = git or GitCommandRunner()
        self._scanner = scanner or SnapshotScanner()

    def build(self, request: SnapshotBuildRequest) -> SnapshotBuildResult:
        repository_url_hash = sha256_text(request.repository_url)
        with tempfile.TemporaryDirectory(prefix="deepdive-snapshot-") as tmp:
            tmp_path = Path(tmp)
            mirror = tmp_path / "repo.git"
            bundle_path = tmp_path / "snapshot.bundle"

            self._git.clone_mirror(request.repository_url, mirror, timeout_seconds=request.timeout_seconds)
            resolved_commit_sha = self._git.resolve_commit(mirror, request.requested_ref, timeout_seconds=request.timeout_seconds)
            tree_sha = self._git.resolve_tree(mirror, resolved_commit_sha, timeout_seconds=request.timeout_seconds)
            tree_entries = self._git.list_tree(mirror, resolved_commit_sha, timeout_seconds=request.timeout_seconds)
            self._git.create_bundle(mirror, resolved_commit_sha, bundle_path, timeout_seconds=request.timeout_seconds)
            bundle_size = bundle_path.stat().st_size
            if bundle_size > request.policy.max_git_bundle_bytes:
                raise SnapshotBuildError(
                    "GitBundleTooLarge",
                    f"GitBundleTooLarge: git bundle size {bundle_size} exceeds max_git_bundle_bytes={request.policy.max_git_bundle_bytes}",
                )

            files, instructions = self._scanner.scan(
                snapshot_id=request.snapshot_id,
                checkout_dir=None,
                tree_entries=tree_entries,
                policy=request.policy,
                storage=request.storage,
                blob_reader=lambda entry: self._git.cat_file_blob(
                    mirror,
                    entry.oid,
                    timeout_seconds=request.timeout_seconds,
                    max_output_bytes=request.policy.max_file_bytes + 1,
                ),
            )
            result = SnapshotBuildResult(
                snapshot_id=request.snapshot_id,
                repository_url_hash=repository_url_hash,
                requested_ref=request.requested_ref,
                resolved_commit_sha=resolved_commit_sha,
                tree_sha=tree_sha,
                snapshot_policy_hash=request.policy.hash,
                manifest_key=manifest_key(request.snapshot_id),
                git_bundle_key=git_bundle_key(repository_url_hash, resolved_commit_sha),
                tree_text_key=tree_text_key(request.snapshot_id),
                file_tree_key=file_tree_key(request.snapshot_id),
                file_count=len(files),
                total_bytes=sum(entry.size_bytes or 0 for entry in files if entry.entry_kind == "file"),
                files=files,
                instructions=instructions,
            )
            request.storage.put_file(result.git_bundle_key, bundle_path, content_type="application/octet-stream")
            request.storage.put_bytes(result.tree_text_key, tree_text(files).encode(), content_type="text/plain; charset=utf-8")
            request.storage.put_bytes(result.file_tree_key, zstd_json_bytes(file_tree_json(files)), content_type="application/json+zstd")
            request.storage.put_bytes(
                result.manifest_key,
                zstd_json_bytes(manifest_json(result=result, policy=request.policy, instructions=instructions)),
                content_type="application/json+zstd",
            )
            return result

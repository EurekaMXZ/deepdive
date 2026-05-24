from __future__ import annotations

import unittest

from backend.ids import new_uuid7
from backend.storage import (
    InMemoryObjectStorage,
    blob_key,
    evidence_key,
    file_tree_key,
    git_bundle_key,
    instruction_key,
    manifest_key,
    tool_result_key,
    tree_text_key,
)


class StorageTest(unittest.TestCase):
    def test_snapshot_object_keys_follow_storage_contract(self) -> None:
        snapshot_id = new_uuid7()
        repo_hash = "sha256:" + "a" * 64
        commit_sha = "b" * 40
        content_hash = "sha256:" + "0123456789abcdef" * 4
        path_hash = "sha256:" + "fedcba9876543210" * 4

        self.assertEqual(git_bundle_key(repo_hash, commit_sha), f"git-bundles/{'a' * 64}/{commit_sha}.bundle")
        self.assertEqual(manifest_key(snapshot_id), f"snapshots/{snapshot_id}/manifest.json.zst")
        self.assertEqual(tree_text_key(snapshot_id), f"snapshots/{snapshot_id}/tree.txt")
        self.assertEqual(file_tree_key(snapshot_id), f"snapshots/{snapshot_id}/file-tree.json.zst")
        self.assertEqual(
            blob_key(content_hash),
            "blobs/sha256/01/23/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )
        self.assertEqual(
            instruction_key(snapshot_id, path_hash),
            f"instructions/{snapshot_id}/fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210.md",
        )
        self.assertEqual(tool_result_key(snapshot_id), f"tool-results/{snapshot_id}.json")
        self.assertEqual(evidence_key(snapshot_id), f"evidence/{snapshot_id}.txt")

    def test_in_memory_storage_persists_uploaded_bytes(self) -> None:
        storage = InMemoryObjectStorage()

        storage.put_bytes("snapshots/example/tree.txt", b"README.md\n", content_type="text/plain")

        self.assertEqual(storage.get_bytes("snapshots/example/tree.txt"), b"README.md\n")
        self.assertEqual(storage.content_types["snapshots/example/tree.txt"], "text/plain")

    def test_in_memory_storage_put_file_streams_from_path(self) -> None:
        import tempfile
        from pathlib import Path

        storage = InMemoryObjectStorage()
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "bundle"
            source.write_bytes(b"bundle bytes")

            storage.put_file("git-bundles/example.bundle", source, content_type="application/octet-stream")

        self.assertEqual(storage.get_bytes("git-bundles/example.bundle"), b"bundle bytes")


if __name__ == "__main__":
    unittest.main()

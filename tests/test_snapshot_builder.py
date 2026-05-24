from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import SnapshotConfig
from backend.ids import new_uuid7
from backend.security.secret_paths import SECRET_PATH_POLICY_VERSION
from backend.snapshot import GitSnapshotBuilder, GitTreeEntry, SnapshotBuildRequest, SnapshotPolicy
from backend.snapshot.scanner import SnapshotScanner
from backend.storage import InMemoryObjectStorage


class SnapshotBuilderTest(unittest.TestCase):
    def test_git_builder_creates_ready_to_store_snapshot_from_git_runner_outputs(self) -> None:
        storage = InMemoryObjectStorage()
        runner = FakeGitRunner()

        result = GitSnapshotBuilder(git=runner).build(
            SnapshotBuildRequest(
                snapshot_id=new_uuid7(),
                repository_url="https://github.com/EurekaMXZ/relaybot",
                requested_ref="HEAD",
                policy=SnapshotPolicy.from_config(SnapshotConfig(max_file_bytes=32)),
                storage=storage,
            )
        )

        self.assertEqual(runner.cloned_repository_url, "https://github.com/EurekaMXZ/relaybot")
        self.assertEqual(result.resolved_commit_sha, "b" * 40)
        self.assertEqual(result.tree_sha, "c" * 40)
        self.assertIn(result.manifest_key, storage.objects)
        self.assertIn(result.git_bundle_key, storage.objects)
        self.assertIn(result.tree_text_key, storage.objects)
        self.assertIn(result.file_tree_key, storage.objects)

        files_by_path = {entry.path: entry for entry in result.files}
        self.assertEqual(files_by_path["backend"].entry_kind, "directory")
        self.assertEqual(files_by_path["backend/app.py"].entry_kind, "file")
        self.assertIsNotNone(files_by_path["backend/app.py"].content_key)
        self.assertFalse(files_by_path["backend/app.py"].is_binary)
        self.assertEqual(files_by_path["backend/app.py"].line_count, 1)
        self.assertTrue(files_by_path["binary.bin"].is_binary)
        self.assertIsNone(files_by_path["binary.bin"].content_key)
        self.assertTrue(files_by_path["large.txt"].is_large)
        self.assertIsNone(files_by_path["large.txt"].content_key)

        self.assertEqual(len(result.instructions), 1)
        instruction = result.instructions[0]
        self.assertEqual(instruction.path, "AGENTS.md")
        self.assertEqual(instruction.scope_path, "")
        self.assertEqual(instruction.depth, 0)
        self.assertEqual(storage.get_bytes(instruction.content_ref), b"Root instructions\n")

    def test_git_builder_uploads_bundle_with_put_file(self) -> None:
        storage = SpyStorage()
        runner = FakeGitRunner()

        result = GitSnapshotBuilder(git=runner).build(
            SnapshotBuildRequest(
                snapshot_id=new_uuid7(),
                repository_url="https://github.com/EurekaMXZ/relaybot",
                requested_ref="HEAD",
                policy=SnapshotPolicy.from_config(SnapshotConfig(max_file_bytes=32)),
                storage=storage,
            )
        )

        self.assertIn((result.git_bundle_key, "application/octet-stream"), storage.put_file_calls)

    def test_git_builder_rejects_bundle_that_exceeds_policy_limit(self) -> None:
        storage = SpyStorage()
        runner = LargeBundleGitRunner()

        with self.assertRaisesRegex(Exception, "GitBundleTooLarge") as raised:
            GitSnapshotBuilder(git=runner).build(
                SnapshotBuildRequest(
                    snapshot_id=new_uuid7(),
                    repository_url="https://github.com/EurekaMXZ/relaybot",
                    requested_ref="HEAD",
                    policy=SnapshotPolicy(max_file_bytes=32, max_git_bundle_bytes=4),
                    storage=storage,
                )
            )

        self.assertEqual(getattr(raised.exception, "code", None), "GitBundleTooLarge")
        self.assertEqual(storage.put_file_calls, [])

    def test_git_builder_reads_blob_content_without_creating_archive(self) -> None:
        storage = InMemoryObjectStorage()
        runner = NoArchiveGitRunner()

        result = GitSnapshotBuilder(git=runner).build(
            SnapshotBuildRequest(
                snapshot_id=new_uuid7(),
                repository_url="https://github.com/EurekaMXZ/relaybot",
                requested_ref="HEAD",
                policy=SnapshotPolicy.from_config(SnapshotConfig(max_file_bytes=32)),
                storage=storage,
            )
        )

        files_by_path = {entry.path: entry for entry in result.files}
        self.assertIsNotNone(files_by_path["backend/app.py"].content_key)
        self.assertEqual(storage.get_bytes(files_by_path["backend/app.py"].content_key), b"print('hello')\n")
        self.assertEqual(runner.cat_file_oids, ["a" * 40, "d" * 40, "e" * 40])
        self.assertEqual(runner.cat_file_limits, [33, 33, 33])
        self.assertFalse(runner.archive_created)

    def test_scanner_skips_reading_large_files_when_git_tree_size_exceeds_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkout_dir = Path(tmpdir)
            (checkout_dir / "large.bin").write_bytes(b"x" * 1024)
            storage = InMemoryObjectStorage()

            original_read_bytes = Path.read_bytes

            def fail_if_large_file_is_read(path: Path) -> bytes:
                if path.name == "large.bin":
                    raise AssertionError("large files must not be read into memory")
                return original_read_bytes(path)

            with patch.object(Path, "read_bytes", fail_if_large_file_is_read):
                files, instructions = SnapshotScanner().scan(
                    snapshot_id=new_uuid7(),
                    checkout_dir=checkout_dir,
                    tree_entries=[
                        GitTreeEntry(
                            mode="100644",
                            kind="blob",
                            oid="a" * 40,
                            size=1024,
                            path="large.bin",
                        )
                    ],
                    policy=SnapshotPolicy(max_file_bytes=16),
                    storage=storage,
                )

        self.assertEqual(instructions, [])
        self.assertEqual(files[0].path, "large.bin")
        self.assertTrue(files[0].is_large)
        self.assertIsNone(files[0].content_key)
        self.assertEqual(storage.objects, {})

    def test_scanner_records_secret_files_as_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkout_dir = Path(tmpdir)
            (checkout_dir / ".env").write_bytes(b"OPENAI_API_KEY=secret\n")
            storage = InMemoryObjectStorage()

            files, instructions = SnapshotScanner().scan(
                snapshot_id=new_uuid7(),
                checkout_dir=checkout_dir,
                tree_entries=[
                    GitTreeEntry(
                        mode="100644",
                        kind="blob",
                        oid="a" * 40,
                        size=22,
                        path=".env",
                    )
                ],
                policy=SnapshotPolicy(max_file_bytes=1024),
                storage=storage,
            )

        self.assertEqual(instructions, [])
        self.assertEqual(files[0].path, ".env")
        self.assertTrue(files[0].is_large)
        self.assertIsNone(files[0].content_key)
        self.assertEqual(storage.objects, {})

    def test_scanner_records_high_confidence_secret_files_as_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkout_dir = Path(tmpdir)
            (checkout_dir / ".docker").mkdir()
            secret_paths = [
                ".git-credentials",
                ".docker/config.json",
                "private.pem",
                "credentials.json",
                "service-account.json",
                "secrets.yaml",
            ]
            for path in secret_paths:
                target = checkout_dir / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"token=secret\n")
            storage = InMemoryObjectStorage()

            files, instructions = SnapshotScanner().scan(
                snapshot_id=new_uuid7(),
                checkout_dir=checkout_dir,
                tree_entries=[
                    GitTreeEntry(
                        mode="100644",
                        kind="blob",
                        oid=str(index) * 40,
                        size=13,
                        path=path,
                    )
                    for index, path in enumerate(secret_paths, start=1)
                ],
                policy=SnapshotPolicy(max_file_bytes=1024),
                storage=storage,
            )

        self.assertEqual(instructions, [])
        files_by_path = {entry.path: entry for entry in files if entry.entry_kind == "file"}
        self.assertEqual(set(files_by_path), set(secret_paths))
        for path in secret_paths:
            with self.subTest(path=path):
                self.assertTrue(files_by_path[path].is_large)
                self.assertIsNone(files_by_path[path].content_key)
        self.assertEqual(storage.objects, {})

    def test_scanner_records_git_directory_files_as_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkout_dir = Path(tmpdir)
            (checkout_dir / ".git").mkdir()
            (checkout_dir / ".git" / "config").write_bytes(b"[credential]\nhelper = store\n")
            storage = InMemoryObjectStorage()

            files, instructions = SnapshotScanner().scan(
                snapshot_id=new_uuid7(),
                checkout_dir=checkout_dir,
                tree_entries=[
                    GitTreeEntry(
                        mode="100644",
                        kind="blob",
                        oid="a" * 40,
                        size=28,
                        path=".git/config",
                    )
                ],
                policy=SnapshotPolicy(max_file_bytes=1024),
                storage=storage,
            )

        self.assertEqual(instructions, [])
        files_by_path = {entry.path: entry for entry in files}
        self.assertEqual(files_by_path[".git"].entry_kind, "directory")
        self.assertEqual(files_by_path[".git/config"].entry_kind, "file")
        self.assertTrue(files_by_path[".git/config"].is_large)
        self.assertIsNone(files_by_path[".git/config"].content_key)
        self.assertEqual(storage.objects, {})

    def test_snapshot_policy_hash_includes_secret_path_policy_version(self) -> None:
        current = SnapshotPolicy(max_file_bytes=1024)
        changed = SnapshotPolicy(max_file_bytes=1024, secret_path_policy_version="different")

        self.assertEqual(current.secret_path_policy_version, SECRET_PATH_POLICY_VERSION)
        self.assertNotEqual(current.hash, changed.hash)

    def test_scanner_counts_last_line_without_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkout_dir = Path(tmpdir)
            (checkout_dir / "README.md").write_bytes(b"one\ntwo")
            storage = InMemoryObjectStorage()

            files, _ = SnapshotScanner().scan(
                snapshot_id=new_uuid7(),
                checkout_dir=checkout_dir,
                tree_entries=[
                    GitTreeEntry(
                        mode="100644",
                        kind="blob",
                        oid="a" * 40,
                        size=7,
                        path="README.md",
                    )
                ],
                policy=SnapshotPolicy(max_file_bytes=1024),
                storage=storage,
            )

        self.assertEqual(files[0].line_count, 2)


class FakeGitRunner:
    def __init__(self) -> None:
        self.cloned_repository_url: str | None = None

    def clone_mirror(self, repository_url: str, mirror_path: Path, *, timeout_seconds: int) -> None:
        del timeout_seconds
        self.cloned_repository_url = repository_url
        mirror_path.mkdir()

    def resolve_commit(self, mirror_path: Path, ref: str, *, timeout_seconds: int) -> str:
        del mirror_path, ref, timeout_seconds
        return "b" * 40

    def resolve_tree(self, mirror_path: Path, commit_sha: str, *, timeout_seconds: int) -> str:
        del mirror_path, commit_sha, timeout_seconds
        return "c" * 40

    def list_tree(self, mirror_path: Path, commit_sha: str, *, timeout_seconds: int) -> list[GitTreeEntry]:
        del mirror_path, commit_sha, timeout_seconds
        return [
            GitTreeEntry(mode="100644", kind="blob", oid="a" * 40, size=18, path="AGENTS.md"),
            GitTreeEntry(mode="100644", kind="blob", oid="d" * 40, size=15, path="backend/app.py"),
            GitTreeEntry(mode="100644", kind="blob", oid="e" * 40, size=8, path="binary.bin"),
            GitTreeEntry(mode="100644", kind="blob", oid="f" * 40, size=80, path="large.txt"),
        ]

    def create_bundle(self, mirror_path: Path, commit_sha: str, output_path: Path, *, timeout_seconds: int) -> None:
        del mirror_path, commit_sha, timeout_seconds
        output_path.write_bytes(b"fake bundle")

    def create_archive(self, mirror_path: Path, commit_sha: str, output_path: Path, *, timeout_seconds: int) -> None:
        del mirror_path, commit_sha, timeout_seconds
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_bytes(b"Root instructions\n")
            (root / "backend").mkdir()
            (root / "backend" / "app.py").write_bytes(b"print('hello')\n")
            (root / "binary.bin").write_bytes(b"\x00\x01binary")
            (root / "large.txt").write_bytes(b"x" * 80)
            with tarfile.open(output_path, "w") as archive:
                for file_path in sorted(root.rglob("*")):
                    archive.add(file_path, arcname=file_path.relative_to(root).as_posix())

    def cat_file_blob(
        self, mirror_path: Path, oid: str, *, timeout_seconds: int, max_output_bytes: int | None = None
    ) -> bytes:
        del mirror_path, timeout_seconds, max_output_bytes
        return {
            "a" * 40: b"Root instructions\n",
            "d" * 40: b"print('hello')\n",
            "e" * 40: b"\x00\x01binary",
            "f" * 40: b"x" * 80,
        }[oid]


class NoArchiveGitRunner(FakeGitRunner):
    def __init__(self) -> None:
        super().__init__()
        self.archive_created = False
        self.cat_file_oids: list[str] = []
        self.cat_file_limits: list[int | None] = []

    def create_archive(self, mirror_path: Path, commit_sha: str, output_path: Path, *, timeout_seconds: int) -> None:
        del mirror_path, commit_sha, output_path, timeout_seconds
        self.archive_created = True
        raise AssertionError("snapshot builder must not create and extract a full git archive")

    def cat_file_blob(
        self, mirror_path: Path, oid: str, *, timeout_seconds: int, max_output_bytes: int | None = None
    ) -> bytes:
        self.cat_file_oids.append(oid)
        self.cat_file_limits.append(max_output_bytes)
        return super().cat_file_blob(
            mirror_path, oid, timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes
        )


class LargeBundleGitRunner(FakeGitRunner):
    def create_bundle(self, mirror_path: Path, commit_sha: str, output_path: Path, *, timeout_seconds: int) -> None:
        del mirror_path, commit_sha, timeout_seconds
        output_path.write_bytes(b"x" * 16)


class SpyStorage(InMemoryObjectStorage):
    def __init__(self) -> None:
        super().__init__()
        self.put_file_calls: list[tuple[str, str]] = []

    def put_file(self, key: str, path: Path, *, content_type: str = "application/octet-stream") -> None:
        self.put_file_calls.append((key, content_type))
        super().put_file(key, path, content_type=content_type)


if __name__ == "__main__":
    unittest.main()

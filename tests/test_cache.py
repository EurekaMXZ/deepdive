from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.cache import LocalSourceCache
from backend.config import CacheConfig
from backend.ids import new_uuid7


class LocalSourceCacheTest(unittest.TestCase):
    def test_cleanup_removes_snapshot_cache_older_than_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LocalSourceCache(root_dir=Path(tmpdir))
            old_snapshot_id = new_uuid7()
            fresh_snapshot_id = new_uuid7()
            old_file = cache.write_file(old_snapshot_id, "backend/old.py", b"old")
            fresh_file = cache.write_file(fresh_snapshot_id, "backend/fresh.py", b"fresh")
            old_time = datetime.now(UTC) - timedelta(days=3)
            old_timestamp = old_time.timestamp()
            snapshot_root = cache.snapshot_root(old_snapshot_id)
            for path in [snapshot_root, old_file, old_file.parent]:
                path.touch(exist_ok=True)
                import os

                os.utime(path, (old_timestamp, old_timestamp))

            removed = cache.cleanup(CacheConfig(root_dir=tmpdir, ttl_days=1, max_worker_cache_bytes=1_000_000))

            self.assertGreaterEqual(removed["removed_snapshots"], 1)
            self.assertFalse(cache.snapshot_root(old_snapshot_id).exists())
            self.assertTrue(fresh_file.exists())

    def test_cleanup_removes_oldest_snapshots_until_disk_free_watermark_is_met(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = LocalSourceCache(root_dir=Path(tmpdir))
            old_snapshot_id = new_uuid7()
            fresh_snapshot_id = new_uuid7()
            old_file = cache.write_file(old_snapshot_id, "backend/old.py", b"old")
            fresh_file = cache.write_file(fresh_snapshot_id, "backend/fresh.py", b"fresh")
            old_timestamp = (datetime.now(UTC) - timedelta(days=1)).timestamp()
            import os

            for path in [cache.snapshot_root(old_snapshot_id), old_file, old_file.parent]:
                os.utime(path, (old_timestamp, old_timestamp))

            with patch("backend.cache.shutil.disk_usage") as disk_usage:
                disk_usage.side_effect = [
                    (100, 95, 5),
                    (100, 80, 20),
                ]

                removed = cache.cleanup(
                    CacheConfig(
                        root_dir=tmpdir,
                        ttl_days=30,
                        max_worker_cache_bytes=1_000_000,
                        min_free_disk_percent=15,
                    )
                )

            self.assertEqual(removed["removed_snapshots"], 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(fresh_file.exists())


if __name__ == "__main__":
    unittest.main()

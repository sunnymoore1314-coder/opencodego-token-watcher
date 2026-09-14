"""缓存模块单测。运行: python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from pathlib import Path

from src.cache import CACHE_SCHEMA, load_cache, save_cache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "monitor_cache.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_load_roundtrip(self):
        data = {"schema": CACHE_SCHEMA, "last_sync": "x", "session_ids": [1], "by_day": {}}
        save_cache(self.path, data)
        self.assertEqual(load_cache(self.path), data)

    def test_load_missing_returns_none(self):
        self.assertIsNone(load_cache(self.tmp / "nope.json"))

    def test_load_corrupted_returns_none(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(load_cache(self.path))

    def test_load_wrong_schema_returns_none(self):
        save_cache(self.path, {"schema": 999})
        self.assertIsNone(load_cache(self.path))

    def test_atomic_no_temp_leftover(self):
        save_cache(self.path, {"schema": CACHE_SCHEMA})
        self.assertFalse(self.path.with_suffix(".tmp").exists())


if __name__ == "__main__":
    unittest.main()

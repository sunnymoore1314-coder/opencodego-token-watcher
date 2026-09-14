"""数据管线单测：用临时 sqlite 造 session 表验证 refresh 全流程。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from src.pipeline import refresh

# session 表结构（与真实 db 一致的关键列）
_SCHEMA = """
CREATE TABLE session (
  id TEXT PRIMARY KEY,
  time_created INTEGER NOT NULL,
  time_updated INTEGER NOT NULL,
  tokens_input INTEGER DEFAULT 0,
  tokens_output INTEGER DEFAULT 0,
  tokens_reasoning INTEGER DEFAULT 0,
  tokens_cache_read INTEGER DEFAULT 0,
  tokens_cache_write INTEGER DEFAULT 0,
  cost REAL DEFAULT 0
)
"""
_EPOCH_DAY = 1786000000000  # 任意毫秒时间戳（归入某一天）


def make_db(path: Path, rows: list[tuple]):
    conn = sqlite3.connect(path)
    conn.execute(_SCHEMA)
    conn.executemany(
        "INSERT INTO session (id, time_created, time_updated, tokens_input,"
        " tokens_output, tokens_reasoning, tokens_cache_read, tokens_cache_write)"
        " VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "opencode.db"
        self.cache = self.tmp / "monitor_cache.json"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_success_roundtrip(self):
        make_db(self.db, [("s1", _EPOCH_DAY, _EPOCH_DAY, 100, 10, 0, 900, 0)])
        by_day, err = refresh(str(self.db), self.cache)
        self.assertIsNone(err)
        day = list(by_day.values())[0]
        self.assertEqual(day.input, 100)    # 实际输入（不含缓存）
        self.assertEqual(day.output, 10)
        self.assertAlmostEqual(day.hit_rate, 90.0)  # 900/(100+900+0)
        self.assertTrue(self.cache.exists())  # 缓存已写

    def test_missing_db_falls_back_to_cache(self):
        # 先成功一次产生缓存，再删掉 db
        make_db(self.db, [("s1", _EPOCH_DAY, _EPOCH_DAY, 100, 0, 0, 0, 0)])
        refresh(str(self.db), self.cache)
        self.db.unlink()
        by_day, err = refresh(str(self.db), self.cache)
        self.assertIsNotNone(err)
        self.assertIsNotNone(by_day)  # 缓存历史仍在
        self.assertEqual(by_day, refresh(str(self.db), self.cache)[0])

    def test_no_db_no_cache(self):
        by_day, err = refresh(str(self.tmp / "nope.db"), self.cache)
        self.assertIsNone(by_day)
        self.assertIn("未找到数据源", err)

    def test_corrupted_db(self):
        self.db.write_bytes(b"not a sqlite file")
        by_day, err = refresh(str(self.db), self.cache)
        self.assertIsNotNone(err)
        self.assertIsNone(by_day)  # 无缓存

    def test_aggregates_multiple_days(self):
        d1, d2 = _EPOCH_DAY, _EPOCH_DAY + 86_400_000  # 第二天
        make_db(self.db, [("s1", d1, d1, 1, 0, 0, 0, 0), ("s2", d2, d2, 2, 0, 0, 0, 0)])
        by_day, err = refresh(str(self.db), self.cache)
        self.assertIsNone(err)
        self.assertEqual(len(by_day), 2)


if __name__ == "__main__":
    unittest.main()

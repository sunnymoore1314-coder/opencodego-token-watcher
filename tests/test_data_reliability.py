"""数据层回归：临时数据库/缓存与模拟网络，不读写个人配置。"""
import datetime
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import cache, config, opencode_cloud as oc, pipeline
from src.aggregator import aggregate_by_day
from src.db_reader import open_db
from tests.test_pipeline import make_db, _EPOCH_DAY
from tests.test_opencode_cloud import FixedDate


class LocalDataTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = self.root / "中文 # 数据.db"
        self.cache = self.root / "cache.json"

    def test_saved_db_path_is_used(self):
        make_db(self.db, [("one", _EPOCH_DAY, _EPOCH_DAY, 12, 3, 0, 0, 0)])
        with mock.patch.object(config, "load_config", return_value={"db_path": str(self.db)}):
            days, error = pipeline.refresh(cache_path=self.cache)
        self.assertIsNone(error)
        self.assertEqual(sum(s.input for s in days.values()), 12)

    def test_uri_special_characters_and_readonly(self):
        make_db(self.db, [])
        conn = open_db(self.db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO session (id,time_created,time_updated) VALUES ('a',1,1)")
        finally:
            conn.close()

    def test_cache_write_failure_keeps_fresh_data(self):
        make_db(self.db, [("one", _EPOCH_DAY, _EPOCH_DAY, 12, 3, 0, 0, 0)])
        with mock.patch.object(cache, "save_cache", side_effect=PermissionError("read only")):
            days, error = pipeline.refresh(str(self.db), self.cache)
        self.assertEqual(sum(s.input for s in days.values()), 12)
        self.assertIn("缓存", error)

    def test_invalid_cache_is_ignored(self):
        for data in ([], None, {"schema": 1},
                     {"schema": 1, "by_day": {"2026-08-12": None}},
                     {"schema": 1, "by_day": {"bad": {}}},
                     {"schema": 1, "by_day": {"2026-08-12": {"input": "bad"}}},
                     {"schema": 1, "by_day": {"2026-08-12": {"input": -1}}}):
            self.cache.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(data=data):
                self.assertIsNone(cache.load_cache(self.cache))
                days, error = pipeline.refresh(str(self.root / "missing.db"), self.cache)
                self.assertIsNone(days)
                self.assertIn("未找到", error)

    def test_created_date_and_null_metrics(self):
        tz = datetime.timezone.utc
        created = int(datetime.datetime(2026, 8, 12, tzinfo=tz).timestamp() * 1000)
        stats = aggregate_by_day([{"time_created": created, "time_updated": created + 86400000,
                                   "tokens_input": None, "tokens_output": None,
                                   "tokens_cache_read": None, "tokens_cache_write": None,
                                   "tokens_reasoning": None}], tz)
        self.assertEqual(list(stats), ["2026-08-12"])
        self.assertEqual(stats["2026-08-12"].input_total, 0)

    def test_failed_read_closes_connection(self):
        make_db(self.db, [])
        conn = mock.Mock()
        with mock.patch.object(pipeline, "open_db", return_value=conn), mock.patch.object(
                pipeline, "fetch_sessions", side_effect=pipeline.DbError("bad schema")):
            pipeline.refresh(str(self.db), self.cache)
        conn.close.assert_called_once()

    def test_offline_cli_reads_explicit_database(self):
        now = int(datetime.datetime.now().timestamp() * 1000)
        make_db(self.db, [("one", now, now, 12, 3, 0, 0, 0)])
        result = subprocess.run([sys.executable, "-X", "utf8", "tools/smoke.py", "--db", str(self.db),
                                 "--offline"], capture_output=True, text=True, encoding="utf-8",
                                cwd=Path(__file__).resolve().parent.parent, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fresh_input=12", result.stdout)
        self.assertIn("SKIP", result.stdout)

    def test_offline_cli_handles_zero_tokens(self):
        make_db(self.db, [])
        result = subprocess.run([sys.executable, "-X", "utf8", "tools/smoke.py", "--db", str(self.db),
                                 "--offline"], capture_output=True, text=True, encoding="utf-8",
                                cwd=Path(__file__).resolve().parent.parent, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fresh_input=0", result.stdout)


class CloudSyncTests(unittest.TestCase):
    def setUp(self):
        self.date_patch = mock.patch.object(oc.datetime, "date", FixedDate)
        self.date_patch.start()
        self.addCleanup(self.date_patch.stop)
        parse_time = oc._parse_time
        tz = datetime.timezone(datetime.timedelta(hours=8))
        patch = mock.patch.object(oc, "_parse_time", side_effect=lambda value: parse_time(value).astimezone(tz))
        patch.start()
        self.addCleanup(patch.stop)

    def _sync(self, old, tokens, costs=None):
        with mock.patch.object(oc, "load_cloud_cache", return_value=old), mock.patch.object(
                oc, "month_tokens", return_value=tokens) as fetch, mock.patch.object(
                oc, "month_costs", return_value=costs or {}), mock.patch.object(oc, "save_cloud_cache") as save:
            result = oc.sync_month("workspace", "cookie")
        return result["by_day"], fetch, save

    def test_tokens_without_cost_are_preserved(self):
        days, _, _ = self._sync({"by_day": {}},
                               {"first_id": "new", "2026-08-12": {"input": 10, "requests": 1}})
        self.assertEqual(days["2026-08-12"]["tokens"]["input"], 10)

    def test_increment_without_new_cost_is_added(self):
        old = {"schema": 5, "workspace_id": "workspace", "first_id": "old", "by_day": {
            "2026-08-12": {"total": 3, "by_model": {}, "tokens": {"input": 10}}}}
        days, _, _ = self._sync(old, {"first_id": "new", "_incremental": True,
                                      "2026-08-12": {"input": 2}})
        self.assertEqual(days["2026-08-12"]["tokens"]["input"], 12)
        self.assertEqual(days["2026-08-12"]["total"], 3)

    def test_full_sync_replaces_instead_of_doubling(self):
        old = {"schema": 5, "workspace_id": "workspace", "first_id": "old", "by_day": {
            "2026-08-12": {"total": 3, "by_model": {}, "tokens": {"input": 10}}}}
        days, _, _ = self._sync(old, {"first_id": "new", "_incremental": False,
                                      "2026-08-12": {"input": 12}},
                                  {"2026-08-12": {"total": 4, "by_model": {}}})
        self.assertEqual(days["2026-08-12"]["tokens"]["input"], 12)

    def test_different_workspace_does_not_mix(self):
        old = {"schema": 5, "workspace_id": "another", "first_id": "old", "by_day": {
            "2026-08-12": {"total": 30, "by_model": {}, "tokens": {"input": 100}}}}
        days, fetch, save = self._sync(old, {"first_id": "new", "2026-08-13": {"input": 2}})
        self.assertNotIn("2026-08-12", days)
        self.assertIsNone(fetch.call_args.kwargs["first_id"])
        self.assertEqual(save.call_args.kwargs["workspace_id"], "workspace")

    def test_pagination_limit_rejects_partial_data(self):
        with mock.patch.object(oc, "fetch_usages", return_value=[
                {"id": "new", "timeCreated": "2026-08-12T00:00:00Z", "inputTokens": 2}]):
            with self.assertRaises(oc.CloudError):
                oc.month_tokens("w", "c", max_pages=1)

    def test_marker_stops_and_duplicates_are_not_counted(self):
        row = {"id": "new", "timeCreated": "2026-08-12T00:00:00Z", "inputTokens": 2}
        with mock.patch.object(oc, "fetch_usages", side_effect=[[row], [row, {"id": "old"}]]) as fetch:
            tokens = oc.month_tokens("w", "c", first_id="old")
        self.assertEqual(fetch.call_count, 2)
        self.assertTrue(tokens["_incremental"])
        self.assertEqual(tokens["2026-08-12"]["input"], 2)
        self.assertEqual(tokens["2026-08-12"]["requests"], 1)

    def test_natural_month_boundary(self):
        with mock.patch.object(oc, "fetch_usages", side_effect=[[
                {"id": "a", "timeCreated": "2026-06-30T00:00:00Z", "inputTokens": 2}]]) as fetch:
            tokens = oc.month_tokens("w", "c", months=2)
        self.assertEqual(fetch.call_count, 1)
        self.assertNotIn("2026-06-30", tokens)

    def test_sync_failure_does_not_write_cache(self):
        with mock.patch.object(oc, "load_cloud_cache", return_value={"by_day": {}}), mock.patch.object(
                oc, "month_costs", return_value={}), mock.patch.object(
                oc, "month_tokens", side_effect=oc.CloudError("network", "failed")), mock.patch.object(
                oc, "save_cloud_cache") as save:
            with self.assertRaises(oc.CloudError):
                oc.sync_month("w", "c")
        save.assert_not_called()

    def test_invalid_token_rejects_batch(self):
        with mock.patch.object(oc, "fetch_usages", return_value=[
                {"id": "new", "timeCreated": "2026-08-12T00:00:00Z", "inputTokens": "oops"}]):
            with self.assertRaises(oc.CloudError) as error:
                oc.month_tokens("w", "c")
        self.assertEqual(error.exception.kind, "parse")

    def test_missing_marker_produces_full_snapshot(self):
        with mock.patch.object(oc, "fetch_usages", side_effect=[[
                {"id": "new", "timeCreated": "2026-08-12T00:00:00Z", "inputTokens": 2}], []]):
            tokens = oc.month_tokens("w", "c", first_id="deleted")
        self.assertFalse(tokens["_incremental"])
        self.assertEqual(tokens["2026-08-12"]["input"], 2)

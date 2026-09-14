"""opencode_cloud 官网费用同步：纯逻辑单测（mock 网络）。"""
import sys
import datetime
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import opencode_cloud as oc


class FixedDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 13)


def setUpModule():
    global _date_patch
    _date_patch = mock.patch.object(oc.datetime, "date", FixedDate)
    _date_patch.start()


def tearDownModule():
    _date_patch.stop()


class TestTzOffset(unittest.TestCase):
    def test_format(self):
        s = oc.tz_offset_str()
        self.assertRegex(s, r"^[+-]\d{2}:\d{2}$")


class TestMonthCosts(unittest.TestCase):
    """month_costs 聚合：cost microcents → 美元，按天+按模型累加。"""

    @mock.patch.object(oc, "fetch_costs")
    def test_aggregate_and_convert(self, mock_costs):
        mock_costs.side_effect = [
            # 本月（第一次调用）
            {"usage": [
                {"date": "2026-08-12", "model": "deepseek-v4-flash (go)",
                 "totalCost": 458_000_000, "keyId": "k1", "plan": "sub"},
                {"date": "2026-08-12", "model": "mimo-v2.5 (go)",
                 "totalCost": 92_000_000, "keyId": "k1", "plan": "sub"},
                {"date": "2026-08-11", "model": "deepseek-v4-flash (go)",
                 "totalCost": 320_000_000, "keyId": None, "plan": None},
                {"date": None, "model": "x", "totalCost": 1},  # 无日期行忽略
            ], "keys": []},
            # 上月（第二次调用）
            {"usage": [
                {"date": "2026-07-31", "model": "mimo-v2.5 (go)",
                 "totalCost": 10_000_000, "keyId": "k1", "plan": None},
            ], "keys": []},
        ]
        got = oc.month_costs("wrk_test", "auth=abc", months=2)
        # 8/12: 4.58 + 0.92 = 5.50
        self.assertAlmostEqual(got["2026-08-12"]["total"], 5.50, places=6)
        self.assertAlmostEqual(got["2026-08-12"]["by_model"]["deepseek-v4-flash (go)"], 4.58)
        self.assertAlmostEqual(got["2026-08-12"]["by_model"]["mimo-v2.5 (go)"], 0.92)
        # 8/11: 3.20
        self.assertAlmostEqual(got["2026-08-11"]["total"], 3.20)
        # 7/31 上月也拉到了
        self.assertAlmostEqual(got["2026-07-31"]["total"], 0.10)
        # 无日期行不产生键
        self.assertNotIn(None, got)
        # 调用参数：本月 + 上月（年份/月份正确）
        self.assertEqual(mock_costs.call_count, 2)
        y1, m1 = mock_costs.call_args_list[0].args[2], mock_costs.call_args_list[0].args[3]
        self.assertEqual((y1, m1), (2026, 7))  # 0-based


class TestMonthTokens(unittest.TestCase):
    """month_tokens：usage.list 分页 → 按天聚合，timeCreated 转本地时区归日。"""

    def setUp(self):
        parse_time = oc._parse_time
        tz = datetime.timezone(datetime.timedelta(hours=8))
        patch = mock.patch.object(oc, "_parse_time", side_effect=lambda value: parse_time(value).astimezone(tz))
        patch.start()
        self.addCleanup(patch.stop)

    @mock.patch.object(oc, "fetch_usages")
    def test_aggregate_and_pages(self, mock_usage):
        mock_usage.side_effect = [
            # 第 1 页（UTC 时间 → 本地 +8 归日）
            [
                {"timeCreated": "2026-08-12T15:00:00.000Z",
                 "model": "deepseek-v4-flash (go)",
                 "inputTokens": 1_000_000, "outputTokens": 200_000,
                 "cacheReadTokens": 50_000_000,
                 "cacheWrite5mTokens": 0, "cacheWrite1hTokens": 0,
                 "reasoningTokens": 10_000},
                {"timeCreated": "2026-08-12T02:00:00.000Z",   # UTC 8/12 02:00 = 本地 8/12 10:00
                 "inputTokens": 500_000, "outputTokens": 50_000,
                 "cacheReadTokens": 10_000_000, "cacheWrite5mTokens": 1,
                 "cacheWrite1hTokens": 2, "reasoningTokens": 0},
            ],
            # 第 2 页（空 → 结束）
            [],
        ]
        got = oc.month_tokens("wrk_test", "auth=abc", months=2)
        day = got["2026-08-12"]
        self.assertEqual(day["input"], 1_500_000)
        self.assertEqual(day["output"], 250_000)
        self.assertEqual(day["cache_read"], 60_000_000)
        self.assertEqual(day["cache_write"], 3)
        self.assertEqual(day["reasoning"], 10_000)
        self.assertEqual(mock_usage.call_count, 2)
        # 分页参数正确
        self.assertEqual(mock_usage.call_args_list[0].args, ("wrk_test", "auth=abc", 0))

    @mock.patch.object(oc, "fetch_usages")
    def test_parse_mysql_format(self, mock_usage):
        mock_usage.side_effect = [
            [{"timeCreated": "2026-08-11 16:00:00", "inputTokens": 7, "cacheReadTokens": 0}],
            [],
        ]
        got = oc.month_tokens("w", "c", months=2)
        self.assertIn("2026-08-12", got)  # UTC 8/11 16:00 = 本地 8/12 00:00
        self.assertEqual(got["2026-08-12"]["input"], 7)


class TestSyncMonth(unittest.TestCase):
    @mock.patch.object(oc, "month_tokens", return_value={"2026-08-12": {"input": 1},
                                                          "first_id": "usg_new"})
    @mock.patch.object(oc, "month_costs", return_value={
        "2026-08-12": {"total": 5.5, "by_model": {"deepseek-v4-flash (go)": 4.58}}})
    @mock.patch.object(oc, "load_cloud_cache", return_value={"by_day": {}, "first_id": None})
    @mock.patch.object(oc, "save_cloud_cache")
    def test_merge(self, mock_save, *_):
        out = oc.sync_month("w", "c")
        day = out["by_day"]["2026-08-12"]
        self.assertAlmostEqual(day["total"], 5.5)
        self.assertEqual(day["tokens"]["input"], 1)
        self.assertTrue(out["last_sync"])
        # first_id 透传到缓存
        self.assertEqual(mock_save.call_args.kwargs.get("first_id"), "usg_new")


class TestErrors(unittest.TestCase):
    """错误分类：网络 / 认证 / 服务端。"""

    @mock.patch.object(oc, "_rpc")
    def test_auth_401(self, mock_rpc):
        mock_rpc.side_effect = oc.CloudError("auth", "未登录或 cookie 已过期，请在官网重新登录后更新 cookie")
        with self.assertRaises(oc.CloudError) as cm:
            oc.fetch_costs("w", "c", 2026, 8)
        self.assertEqual(cm.exception.kind, "auth")

    @mock.patch.object(oc, "_rpc")
    def test_network(self, mock_rpc):
        mock_rpc.side_effect = oc.CloudError("network", "无法连接官网")
        with self.assertRaises(oc.CloudError) as cm:
            oc.month_costs("w", "c")
        self.assertEqual(cm.exception.kind, "network")

    def test_parse_bad_shape(self):
        # 非 dict 列表按空数据处理（新协议容错）
        with mock.patch.object(oc, "_rpc", return_value=[1, 2, 3]):
            data = oc.fetch_costs("w", "c", 2026, 8)
            self.assertEqual(data["usage"], [])
            self.assertEqual(data["keys"], [])


class TestCache(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name) / "nested" / "monitor_cloud.json"
        self.orig = oc.get_cloud_cache_path

        def fake():
            return self.tmp
        oc.get_cloud_cache_path = fake

    def tearDown(self):
        oc.get_cloud_cache_path = self.orig
        self.tmp.unlink(missing_ok=True)

    def test_roundtrip(self):
        oc.save_cloud_cache({"2026-08-12": {"total": 5.5, "by_model": {"m": 5.5}}})
        data = oc.load_cloud_cache()
        self.assertAlmostEqual(data["by_day"]["2026-08-12"]["total"], 5.5)
        self.assertTrue(data["last_sync"])

    def test_invalid_structure_returns_empty(self):
        self.tmp.parent.mkdir(parents=True)
        for raw in ('[]', '{"schema":5,"by_day":{"2026-08-12":null}}',
                    '{"schema":5,"by_day":{"bad-date":{}}}'):
            self.tmp.write_text(raw, encoding="utf-8")
            self.assertEqual(oc.load_cloud_cache()["by_day"], {})

    def test_missing_timestamp_is_normalized(self):
        self.tmp.parent.mkdir(parents=True)
        self.tmp.write_text('{"schema":5,"by_day":{}}', encoding="utf-8")
        self.assertIsNone(oc.load_cloud_cache()["last_sync"])

    def test_missing_returns_empty(self):
        data = oc.load_cloud_cache()
        self.assertEqual(data, {"by_day": {}, "last_sync": None})


class TestParseStream(unittest.TestCase):
    """seroval 流解析：对象/数组/嵌套引用/new Date。"""

    def test_usage_list_stream(self):
        raw = b';0x0000002c;((self.$R=self.$R||{})["server-fn:0"]=[],($R=>$R[0]=[$R[1]={id:"usg_1",model:"m",inputTokens:5,cost:100,timeCreated:$R[2]=new Date("2026-08-12T10:00:00.000Z"),enrichment:$R[3]={plan:"lite"}}])($R["server-fn:0"]))'
        rows = oc._parse_stream(raw)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["id"], "usg_1")
        self.assertEqual(r["inputTokens"], 5)
        self.assertEqual(r["cost"], 100)
        self.assertEqual(r["timeCreated"], "2026-08-12T10:00:00.000Z")
        self.assertEqual(r["enrichment"]["plan"], "lite")

    def test_costs_stream(self):
        raw = b';0x1f;((self.$R=self.$R||{})["server-fn:0"]=[],($R=>$R[0]={usage:$R[1]=[$R[2]={date:"2026-08-12",model:"m",totalCost:458000000,plan:"sub"}],keys:$R[3]=[]})($R["server-fn:0"]))'
        rows = oc._parse_stream(raw)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-08-12")
        self.assertEqual(rows[0]["totalCost"], 458000000)


class TestSerovalNode(unittest.TestCase):
    def test_types(self):
        self.assertEqual(oc._seroval_node("abc"), {"t": 1, "s": "abc"})
        self.assertEqual(oc._seroval_node(7), {"t": 0, "s": 7})
        self.assertEqual(oc._seroval_node(None), {"t": 2, "s": 0})
        self.assertEqual(oc._seroval_node(True), {"t": 2, "s": 2})
        self.assertEqual(oc._seroval_node(["a", 1]), {"t": 9, "l": 2, "a": [{"t": 1, "s": "a"}, {"t": 0, "s": 1}]})


if __name__ == "__main__":
    unittest.main()

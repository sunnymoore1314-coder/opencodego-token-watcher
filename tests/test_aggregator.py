"""聚合模块单测（纯函数，无 db/UI 依赖）。运行: python -m unittest discover -s tests"""
import datetime
import unittest

from src.aggregator import (
    DayStats,
    aggregate_by_day,
    aggregate_month,
    aggregate_week,
    format_tokens,
)

TZ = datetime.timezone(datetime.timedelta(hours=8))  # 固定 +08:00，测试可复现


def ms(y, m, d, h=12):
    return int(datetime.datetime(y, m, d, h, tzinfo=TZ).timestamp() * 1000)


def session(tokens_input=0, tokens_output=0, cache_read=0, cache_write=0, day=None):
    return {
        "time_updated": ms(*day) if day else ms(2026, 8, 12),
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "tokens_cache_read": cache_read,
        "tokens_cache_write": cache_write,
    }


class TestAggregateByDay(unittest.TestCase):
    def test_input_is_fresh(self):
        """输入 = 新鲜输入（实际发送口径，不含缓存）。"""
        s = [session(tokens_input=100, cache_read=900, cache_write=10, day=(2026, 8, 12))]
        by_day = aggregate_by_day(s, TZ)
        d = by_day["2026-08-12"]
        self.assertEqual(d.input, 100)
        self.assertEqual(d.cache_read, 900)
        self.assertEqual(d.output, 0)

    def test_group_by_day(self):
        s = [session(tokens_input=1, day=(2026, 8, 11)), session(tokens_input=2, day=(2026, 8, 12))]
        by_day = aggregate_by_day(s, TZ)
        self.assertEqual(set(by_day), {"2026-08-11", "2026-08-12"})
        self.assertEqual(by_day["2026-08-11"].input, 1)
        self.assertEqual(by_day["2026-08-12"].input, 2)

    def test_same_day_sums(self):
        s = [session(tokens_input=1, day=(2026, 8, 12)), session(tokens_input=2, day=(2026, 8, 12))]
        self.assertEqual(aggregate_by_day(s, TZ)["2026-08-12"].input, 3)

    def test_empty(self):
        self.assertEqual(aggregate_by_day([], TZ), {})


class TestAggregateWeek(unittest.TestCase):
    def test_monday_start(self):
        """2026-08-10 是周一：周日 8/16 与周一 8/10 同周，key 为周一日期。"""
        s = [session(tokens_input=1, day=(2026, 8, 10)), session(tokens_input=9, day=(2026, 8, 16))]
        weeks = aggregate_week(aggregate_by_day(s, TZ))
        self.assertEqual(weeks, {"2026-08-10": DayStats(input=10, requests=2)})  # 两天各 1 会话

    def test_sunday_before_belongs_to_prev_week(self):
        """8/9（周日）属于 8/3 那周；8/10（周一）开新周。"""
        s = [session(tokens_input=1, day=(2026, 8, 9)), session(tokens_input=2, day=(2026, 8, 10))]
        weeks = aggregate_week(aggregate_by_day(s, TZ))
        self.assertEqual(weeks, {"2026-08-03": DayStats(input=1, requests=1), "2026-08-10": DayStats(input=2, requests=1)})


class TestAggregateMonth(unittest.TestCase):
    def test_month_key(self):
        s = [session(tokens_input=1, day=(2026, 7, 31)), session(tokens_input=2, day=(2026, 8, 1))]
        months = aggregate_month(aggregate_by_day(s, TZ))
        self.assertEqual(months, {"2026-07": DayStats(input=1, requests=1), "2026-08": DayStats(input=2, requests=1)})


class TestHitRate(unittest.TestCase):
    def test_normal(self):
        d = DayStats(input=100, cache_read=900, cache_write=0)
        self.assertAlmostEqual(d.hit_rate, 90.0)  # 900 / (100+900+0)

    def test_zero_denominator(self):
        self.assertIsNone(DayStats().hit_rate)


class TestFormatTokens(unittest.TestCase):
    def test_small(self):
        self.assertEqual(format_tokens(999), "999")
        self.assertEqual(format_tokens(0), "0")

    def test_thousands(self):
        self.assertEqual(format_tokens(1000), "1.0K")
        self.assertEqual(format_tokens(89123), "89.1K")

    def test_millions(self):
        self.assertEqual(format_tokens(1_234_567), "1.2M")
        self.assertEqual(format_tokens(1_000_000), "1.0M")


if __name__ == "__main__":
    unittest.main()

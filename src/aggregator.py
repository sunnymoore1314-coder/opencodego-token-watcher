"""聚合模块：会话记录 → 日/周/月聚合 + 命中率。纯函数，不依赖 db/UI，可单测。"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DayStats:
    """单日聚合结果（官网计价口径，2026-08-13 用户确认）。

    input 为新鲜输入（缓存读单独计）；总输入 = input + cache_read + cache_write。
    requests：官网口径请求次数（usage.list 记录数；本地近似为会话数）。
    """
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0
    cost: float = 0.0
    requests: int = 0

    @property
    def input_total(self) -> int:
        """总输入（官网 usage 表 input 列口径）：新鲜 + 缓存读 + 缓存写。"""
        return self.input + self.cache_read + self.cache_write

    @property
    def total(self) -> int:
        """总 token：总输入 + 输出 + 推理。"""
        return self.input_total + self.output + self.reasoning

    @property
    def hit_rate(self) -> float | None:
        """缓存命中率（官网同口径）：cache_read / 总输入，总输入为 0 时返回 None。"""
        total = self.input_total
        if total <= 0:
            return None
        return self.cache_read / total * 100.0


def aggregate_by_day(sessions: list[dict], tz: datetime.tzinfo | None = None) -> dict[str, DayStats]:
    """按会话 time_created 归入自然日，缺失时回退 time_updated。

    sessions: [{time_updated(ms), tokens_input, tokens_output,
                tokens_cache_read, tokens_cache_write}]
    返回: {"YYYY-MM-DD": DayStats}
    """
    by_day: dict[str, DayStats] = {}
    for s in sessions:
        ms = s.get("time_created") or s.get("time_updated") or 0  # 与官网口径一致（time_updated 跨天漂移）
        day = datetime.datetime.fromtimestamp(ms / 1000, tz).date().isoformat()
        fresh = int(s.get("tokens_input") or 0)
        cr = int(s.get("tokens_cache_read") or 0)
        cw = int(s.get("tokens_cache_write") or 0)
        cur = by_day.get(day, DayStats())
        by_day[day] = DayStats(
            input=cur.input + fresh,  # 新鲜输入（缓存读单独计）
            output=cur.output + int(s.get("tokens_output") or 0),
            cache_read=cur.cache_read + cr,
            cache_write=cur.cache_write + cw,
            reasoning=cur.reasoning + int(s.get("tokens_reasoning") or 0),
            cost=cur.cost + float(s.get("cost", 0) or 0),
            requests=cur.requests + 1,  # 本地近似：会话数
        )
    return by_day


def _week_start(d: datetime.date) -> datetime.date:
    """周一起算的周起始日。"""
    return d - datetime.timedelta(days=d.weekday())


def aggregate_week(by_day: dict[str, DayStats]) -> dict[str, DayStats]:
    """by_day → 按周聚合（周一为起始），key 为该周周一的日期 "YYYY-MM-DD"。"""
    weeks: dict[str, DayStats] = {}
    for day, stats in by_day.items():
        d = datetime.date.fromisoformat(day)
        wk = _week_start(d).isoformat()
        cur = weeks.get(wk, DayStats())
        weeks[wk] = DayStats(
            input=cur.input + stats.input,
            output=cur.output + stats.output,
            cache_read=cur.cache_read + stats.cache_read,
            cache_write=cur.cache_write + stats.cache_write,
            reasoning=cur.reasoning + stats.reasoning,
            cost=cur.cost + stats.cost,
            requests=cur.requests + stats.requests,
        )
    return weeks


def aggregate_month(by_day: dict[str, DayStats]) -> dict[str, DayStats]:
    """by_day → 按月聚合，key 为 "YYYY-MM"。"""
    months: dict[str, DayStats] = {}
    for day, stats in by_day.items():
        mk = day[:7]
        cur = months.get(mk, DayStats())
        months[mk] = DayStats(
            input=cur.input + stats.input,
            output=cur.output + stats.output,
            cache_read=cur.cache_read + stats.cache_read,
            cache_write=cur.cache_write + stats.cache_write,
            reasoning=cur.reasoning + stats.reasoning,
            cost=cur.cost + stats.cost,
            requests=cur.requests + stats.requests,
        )
    return months


def format_tokens(n: int) -> str:
    """大数缩写：<1000 原样；≥1000 → 1.2K；≥1_000_000 → 1.3M。"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)

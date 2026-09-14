"""数据管线：读 db → 聚合 → 写缓存 → 返回 by_day。

db 失败时回退缓存历史（db 损坏/锁定/不存在时 UI 仍可显示历史）。
"""
from __future__ import annotations

import datetime
from pathlib import Path

from src import cache as cache_mod
from src import config
from src.aggregator import DayStats, aggregate_by_day
from src.db_reader import DbError, fetch_sessions, open_db


def refresh(db_path: str | None = None,
            cache_path: Path | None = None) -> tuple[dict | None, str | None]:
    """拉取最新用量。返回 (by_day, error)。

    by_day: {"YYYY-MM-DD": DayStats}（统一为 DayStats 对象），失败回退缓存时仍非 None；
    error: None 表示成功；否则为可展示的错误信息。
    """
    cache_path = cache_path or config.get_cache_path()

    def _from_cache():
        data = cache_mod.load_cache(cache_path)
        if not data:
            return None
        return {d: DayStats(**s) for d, s in data["by_day"].items()}

    if db_path is None:
        db_path = config.load_config().get("db_path")
    p = config.detect_db(db_path)
    if p is None:
        return _from_cache(), "未找到数据源，请在设置中指定 opencode.db 路径"
    try:
        conn = open_db(p)
        try:
            sessions = fetch_sessions(conn)
        finally:
            conn.close()
    except DbError as e:
        return _from_cache(), f"读取失败（显示缓存历史）: {e}"
    by_day = aggregate_by_day(sessions)
    try:
        cache_mod.save_cache(cache_path, {
            "schema": cache_mod.CACHE_SCHEMA,
            "last_sync": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "session_ids": [s["id"] for s in sessions],
            "by_day": {d: vars(s) for d, s in by_day.items()},
        })
    except OSError as e:
        return by_day, f"数据已读取，但无法保存缓存: {e}"
    return by_day, None

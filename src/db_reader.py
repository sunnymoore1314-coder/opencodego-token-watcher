"""db 读取模块：只读打开 opencode.db，取出 session 表的 token 聚合字段。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# session 表官方已聚合好的 token 字段（阶段 1 实测与 message JSON / stats 三方一致）
_SESSION_COLS = (
    "id", "time_created", "time_updated",
    "tokens_input", "tokens_output", "tokens_reasoning",
    "tokens_cache_read", "tokens_cache_write", "cost",
)
_SESSION_SQL = (
    f"SELECT {', '.join(_SESSION_COLS)} FROM session ORDER BY time_updated"
)


class DbError(Exception):
    """db 打开/读取失败（不存在、损坏、锁定等）。"""


def open_db(path: Path) -> sqlite3.Connection:
    """只读打开 db（URI mode=ro），失败抛 DbError。"""
    try:
        return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise DbError(f"无法打开数据库 {path}: {e}") from e


def fetch_sessions(conn: sqlite3.Connection) -> list[dict]:
    """读全部会话记录（session 表很小，全量读毫秒级）。"""
    try:
        rows = conn.execute(_SESSION_SQL).fetchall()
    except sqlite3.Error as e:
        raise DbError(f"读取 session 表失败: {e}") from e
    return [dict(zip(_SESSION_COLS, r)) for r in rows]

"""缓存模块：by_day 聚合结果 JSON 缓存，原子写。"""
from __future__ import annotations

import json
import datetime
import math
import tempfile
from pathlib import Path

from src.aggregator import DayStats

CACHE_SCHEMA = 1


def valid_day(day) -> bool:
    if not isinstance(day, str):
        return False
    try:
        return datetime.date.fromisoformat(day).isoformat() == day
    except ValueError:
        return False


def valid_stats(stats) -> bool:
    """旧缓存可缺新增字段；非数值/负数/非有限数和未知字段视为损坏。"""
    if not isinstance(stats, dict):
        return False
    for key, value in stats.items():
        if key not in DayStats.__dataclass_fields__:
            return False
        if key == "cost":
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return False
        elif type(value) is not int or value < 0:
            return False
    return True


def load_cache(path: Path) -> dict | None:
    """读缓存；不存在或损坏返回 None。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if (isinstance(data, dict) and data.get("schema") == CACHE_SCHEMA
                and isinstance(data.get("by_day"), dict)
                and all(valid_day(day) and valid_stats(stats)
                        for day, stats in data["by_day"].items())):
            return data
    except (OSError, ValueError):
        pass
    return None


def save_cache(path: Path, data: dict) -> None:
    """原子写：先写临时文件再 rename，避免半成品覆盖（旧会话踩过的竞态坑）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp",
                                         delete=False) as f:
            tmp = Path(f.name)
            json.dump(data, f, ensure_ascii=False, allow_nan=False)
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

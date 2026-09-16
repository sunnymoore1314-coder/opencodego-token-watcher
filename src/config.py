"""配置模块：数据目录、config.json 读写、db 路径探测、开机自启。"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

from src.cache import save_cache

APP_NAME = "opencodego-token-watcher"

# 默认探测顺序：config 里的 db_path → 默认路径 → 备选路径
_DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
_ALT_DBS = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "opencode" / "opencode.db",
    Path(os.environ.get("APPDATA", "")) / "opencode" / "opencode.db",
]


def get_data_dir() -> Path:
    """数据目录：Windows 用 %APPDATA%\\opencodego-token-watcher。"""
    base = os.environ.get("APPDATA") if sys.platform == "win32" else None
    if base:
        return Path(base) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def get_config_path() -> Path:
    return get_data_dir() / "config.json"


def get_cache_path() -> Path:
    return get_data_dir() / "monitor_cache.json"


def default_config() -> dict:
    return {"db_path": None, "autostart": False, "window_pos": None,
            "theme": "system", "window_alpha": 0.78,
            "refresh_interval": 1, "number_format": "abbr",
            "topmost_on_start": True, "lock_position": False,
            "display_fields": ["input_total", "output", "hit_rate", "cost"],
            "window_size": None, "tips_shown": False,
            "click_through": False,
            "cloud_workspace_id": "", "cloud_cookie": "", "cloud_enabled": False}


def load_config() -> dict:
    cfg = default_config()
    try:
        with open(get_config_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in cfg})
    except (OSError, ValueError):
        pass  # 无配置或损坏 → 默认值
    # 迁移：异常值恢复默认（早期 radio bug 写入过 "0"）
    if cfg.get("theme") not in ("system", "light", "dark"):
        cfg["theme"] = "system"
    if cfg.get("number_format") not in ("abbr", "plain"):
        cfg["number_format"] = "abbr"
    defaults = default_config()
    for key in ("autostart", "topmost_on_start", "lock_position", "click_through",
                "cloud_enabled", "tips_shown"):
        if type(cfg[key]) is not bool:
            cfg[key] = defaults[key]
    for key in ("db_path", "cloud_workspace_id", "cloud_cookie"):
        if not isinstance(cfg[key], str):
            cfg[key] = defaults[key]
    for key, low, high in (("window_alpha", 0.50, 0.95), ("refresh_interval", 1, 30)):
        value = cfg[key]
        if type(value) not in (int, float) or not math.isfinite(value):
            value = defaults[key]
        value = min(high, max(low, value))
        cfg[key] = int(value) if key == "refresh_interval" else value
    for key in ("window_pos", "window_size"):
        value = cfg[key]
        if not (isinstance(value, list) and len(value) == 2
                and all(type(v) is int for v in value)):
            cfg[key] = None
        elif key == "window_size":
            cfg[key] = [min(600, max(180, value[0])), min(560, max(120, value[1]))]
    fields = cfg.get("display_fields")
    allowed = ("input_total", "output", "hit_rate", "cost", "input_fresh", "cache_read",
               "cache_write", "reasoning", "total", "requests")
    cleaned = []
    if isinstance(fields, list):
        for field in fields:
            field = "input_total" if field == "input" else field
            if field in allowed and field not in cleaned:
                cleaned.append(field)
    cfg["display_fields"] = cleaned or defaults["display_fields"]
    return cfg


def save_config(cfg: dict) -> None:
    save_cache(get_config_path(), cfg)


def detect_db(explicit: str | None = None) -> Path | None:
    """探测 db 路径。显式指定时只查该路径（不存在则 None，不 fallback）；
    未指定时按 默认 → 备选 顺序找第一个存在的。"""
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    for p in [_DEFAULT_DB, *_ALT_DBS]:
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


# ---------- 开机自启（HKCU Run 键） ----------
def _autostart_cmd() -> str:
    """自启命令：打包后为 exe 路径；开发期为 python + main.py。"""
    if getattr(sys, "frozen", False):  # PyInstaller
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{Path(sys.argv[0]).resolve()}"'


def set_autostart(enabled: bool) -> bool:
    """写/删 HKCU Run 键。返回是否成功（非 Windows 返回 False）。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE)
        try:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _autostart_cmd())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)
        return True
    except OSError:
        return False

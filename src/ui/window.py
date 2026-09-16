"""主窗口：tkinter 迷你悬浮小窗，Windows 剪贴板风白色圆角卡片。

实现：Canvas 全窗口绘制（圆角卡片 + 文字 + 进度条），
窗口背景用 -transparentcolor 抠色（四角圆角外完全透明），
整体 -alpha 半透明。真 Acrylic 在 tkinter 上实测内容丢失，弃用。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import datetime
import threading
import tkinter as tk

from src import config, opencode_cloud, pipeline, theme
from src.aggregator import DayStats, aggregate_month, aggregate_week, format_tokens
from src.ui.settings import Settings
from src.ui.tray import TrayIcon

# ---- 样式（Apple 风格深浅色：docs/03-设计规范/ui-spec.md；配色见 src/theme.py）----
KEY = theme.KEY               # 抠色：圆角外区域完全透明
FONT_NUM = ("Segoe UI", 10, "normal")  # 数字：与标签（9）同风格，不加粗（用户要求）
FONT_LABEL = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
W = 250
H = 182
MIN_W, MIN_H = 180, 120
MAX_W, MAX_H = 600, 560
RADIUS = 18                   # 卡片圆角（Apple 大圆角）
PAD = 16                      # 内容左右边距
WEEKDAYS = "一二三四五六日"
GRAN_LABELS = {"day": "日", "week": "周", "month": "月"}


def _round_rect(cv: tk.Canvas, x1: int, y1: int, x2: int, y2: int,
                r: int, **kw) -> int:
    """smooth 多边形画圆角矩形，返回 item id。"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# 显示要素（官网计价口径，2026-08-13 用户确认）：
# input_total 总输入（新鲜+缓存读+缓存写）/ output / hit_rate / cost 为默认四项
FIELD_LABELS = {
    "input_total": "输入",      # 总输入（官网 usage 表 input 列口径）
    "output": "输出",
    "hit_rate": "命中率",
    "cost": "费用",
    "input_fresh": "新鲜输入",  # 计费主体（不含缓存）
    "cache_read": "缓存读",
    "cache_write": "缓存写",
    "reasoning": "推理",
    "total": "总 token",
    "requests": "请求次数",
}
DEFAULT_FIELDS = ["input_total", "output", "hit_rate", "cost"]


def _as_stats(s) -> DayStats | None:
    """兼容 dict / DayStats / None。"""
    if s is None:
        return None
    return s if isinstance(s, DayStats) else DayStats(**s)


# ---- Windows 任务栏可见性（ctypes，零依赖）----
# 任务栏按钮由 shell 在窗口重新显示时重评估：改 exstyle 后必须 hide/show 刷新。
# 64 位安全：Get/SetWindowLongPtrW 必须显式声明 HWND/LONG_PTR 类型，
# 否则 HWND 被截断成 32 位静默失败。
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x80       # 置顶开：隐藏任务栏按钮
WS_EX_APPWINDOW = 0x40000     # 置顶关：强制显示任务栏按钮
SWP_FRAMECHANGED = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020  # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
GA_ROOT = 2


def _root_hwnd(widget) -> int:
    """顶层窗口 HWND（GetAncestor GA_ROOT；GetParent 对 overrideredirect 窗口可能返回 NULL）。"""
    try:
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = (ctypes.wintypes.HWND, ctypes.c_uint)
        user32.GetAncestor.restype = ctypes.wintypes.HWND
        return int(user32.GetAncestor(widget.winfo_id(), GA_ROOT)) or int(widget.winfo_id())
    except Exception:
        return int(widget.winfo_id())


def _set_taskbar_visible(hwnd: int, show: bool) -> None:
    """控制顶层窗口是否在任务栏显示按钮（show=True 显示）。

    显示：清 TOOLWINDOW + 加 APPWINDOW，hide/show 强制 shell 重评估；
    隐藏：加 TOOLWINDOW + 清 APPWINDOW（按钮消失无需 hide/show）。
    均以 SetWindowPos(FRAMECHANGED) 重申非客户区。
    """
    if not hwnd:
        return
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.argtypes = (ctypes.wintypes.HWND, ctypes.c_int)
        user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        user32.SetWindowLongPtrW.argtypes = (ctypes.wintypes.HWND, ctypes.c_int, ctypes.c_longlong)
        user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if show:
            ex = (ex | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        else:
            ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
        if show:  # 任务栏按钮只在窗口重新显示时重评估
            user32.ShowWindow.argtypes = (ctypes.wintypes.HWND, ctypes.c_int)
            user32.ShowWindow(hwnd, 0)  # SW_HIDE
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
        user32.SetWindowPos.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.HWND,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_uint)
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_FRAMECHANGED)
    except Exception:
        pass


class UsageWindow(tk.Tk):
    """迷你悬浮小窗。"""

    def __init__(self):
        super().__init__()
        cfg = config.load_config()
        self.title("OpenCodeGO Token Watcher")
        # 尺寸：保留用户宽度；高度会在 render() 中按全部内容自动展开。
        size = cfg.get("window_size")
        self._sw = min(MAX_W, max(MIN_W, int(size[0]) if size else W))
        self._sh = min(MAX_H, max(MIN_H, int(size[1]) if size else H))
        self.geometry(f"{self._sw}x{self._sh}")
        self.configure(bg=KEY)
        self.attributes("-topmost", cfg.get("topmost_on_start", True))  # 置顶（设置窗可改）
        self.attributes("-alpha", cfg.get("window_alpha", 0.78))  # 半透明（设置窗可调）
        self.attributes("-transparentcolor", KEY)  # 抠色 → 圆角外完全透明
        self.overrideredirect(True)                # 无边框悬浮窗
        self._no_activate()                        # 不抢用户焦点
        pos = cfg.get("window_pos")
        if pos:
            self.geometry(f"+{pos[0]}+{pos[1]}")   # 恢复上次位置
        # 视图状态
        self.gran = "day"
        self.cursor = datetime.date.today()
        self.by_day: dict | None = None
        self.last_error: str | None = None
        self._sync_time = ""
        # 官网费用同步（费用以 opencode.ai 官网为准）
        self._cloud_ws = cfg.get("cloud_workspace_id") or ""
        self._cloud_cookie = cfg.get("cloud_cookie") or ""
        self._cloud_enabled = bool(cfg.get("cloud_enabled", False))
        self._cloud_err: str | None = None
        _cd = opencode_cloud.load_cloud_cache()
        self._cloud_by_day: dict = _cd["by_day"]
        self._cloud_sync_at: str | None = _cd["last_sync"]
        # 行为设置（设置窗可改）
        self._refresh_ms = int(cfg.get("refresh_interval", 1)) * 60_000  # 自动刷新周期
        self._refresh_after: str | None = None     # 当前 after 链 id（改周期时先取消）
        self._number_format = cfg.get("number_format", "abbr")  # abbr 缩写 / plain 千分位
        self._lock_position = bool(cfg.get("lock_position", False))  # 锁定拖动
        _fields = cfg.get("display_fields", DEFAULT_FIELDS)
        if "input" in _fields and "input_total" not in _fields:  # 旧配置迁移
            _fields = ["input_total" if f == "input" else f for f in _fields]
        self._display_fields = list(_fields)  # 显示哪些行
        self._click_through = bool(cfg.get("click_through", False))  # 鼠标穿透
        # 主题（默认跟随系统）
        self.theme_cfg = cfg.get("theme", "system")
        self.C = theme.get_palette(self.theme_cfg)
        # 画布
        self.canvas = tk.Canvas(self, width=self._sw, height=self._sh, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._bind_drag()
        self._bind_actions()
        self._bind_menu()
        self.after(200, self.refresh)                      # 启动即刷新
        self._refresh_after = self.after(self._refresh_ms, self._auto_refresh)  # 周期自动刷新
        self.after(1200, self._maybe_show_tips)            # 首次上手提示
        self.after(5000, self._keep_topmost)               # 置顶防失效（5 秒后首轮）
        self.after(2000, self._pos_check)                  # 防丢屏外（2 秒轮询）
        self._register_hotkeys()                           # 全局热键（穿透恢复/快捷设置）
        if self._cloud_enabled and self._cloud_ws and self._cloud_cookie:
            self.after(3000, self.sync_cloud)              # 启动后自动同步官网数据
        self._init_tray()                                  # 系统托盘图标（关闭/找回入口）

    # ---------- 稳定性（参考 TrafficMonitor：置顶防失效 / 防丢屏外） ----------
    def _keep_topmost(self) -> None:
        """置顶防失效：置顶开启时定期 SetWindowPos 重申（防全屏应用抢占），每 5 分钟。"""
        try:
            if self.attributes("-topmost"):
                hwnd = _root_hwnd(self)
                ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)
        except Exception:
            pass
        self.after(5 * 60_000, self._keep_topmost)

    def _pos_check(self) -> None:
        """防丢屏外：窗口完全在屏幕外时拉回屏内（显示器拔插/分辨率变化场景）。"""
        try:
            x, y = self.winfo_x(), self.winfo_y()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            if x > sw - 20 or y > sh - 20 or x + self._sw < 20 or y + self._sh < 20:
                nx = min(max(x, 0), max(0, sw - self._sw))
                ny = min(max(y, 0), max(0, sh - self._sh))
                self.geometry(f"+{nx}+{ny}")
        except Exception:
            pass
        self.after(2000, self._pos_check)

    # ---------- 首次上手提示 ----------
    def _maybe_show_tips(self) -> None:
        """一次性提示条（Apple 风格 toast）：右键菜单 + 拖动 + 缩放。"""
        cfg = config.load_config()
        if cfg.get("tips_shown"):
            return
        cfg["tips_shown"] = True
        config.save_config(cfg)
        tip = tk.Toplevel(self)
        tip.overrideredirect(True)
        tip.configure(bg=KEY)
        tip.attributes("-topmost", True)
        tip.attributes("-alpha", 0.95)
        tip.attributes("-transparentcolor", KEY)
        tw, th = 300, 44
        cv = tk.Canvas(tip, width=tw, height=th, bg=KEY, highlightthickness=0, bd=0)
        cv.pack()
        _round_rect(cv, 4, 4, tw - 4, th - 4, 12, fill=self.C["card"], outline="")
        cv.create_text(tw / 2, th / 2, font=("Segoe UI", 9), fill=self.C["main"],
                       text="💡 右键呼出菜单 · 拖动卡片移动 · 拖右下角缩放")
        tip.update_idletasks()
        x = self.winfo_rootx() + (self._sw - tw) // 2
        y = self.winfo_rooty() + self._sh + 6
        tip.geometry(f"+{max(0, x)}+{y}")
        tip.after(8000, tip.destroy)

    # ---------- 外观 ----------
    def set_appearance(self, theme_cfg=None, alpha=None) -> None:
        """设置窗保存后调用：按需更新主题/透明度并重绘。None 参数保持原值。"""
        if theme_cfg is not None:
            self.theme_cfg = theme_cfg
            self.C = theme.get_palette(theme_cfg)
        if alpha is not None:
            self.attributes("-alpha", float(alpha))
        self.render()

    # ---------- 数据刷新 ----------
    def refresh(self) -> None:
        """后台线程拉数据，回主线程渲染。"""

        def work():
            by_day, err = pipeline.refresh()
            self.after(0, lambda: self.set_data(by_day, err))

        threading.Thread(target=work, daemon=True).start()

    def set_data(self, by_day, error) -> None:
        self.by_day, self.last_error = by_day, error
        self._sync_time = datetime.datetime.now().strftime("%H:%M") if error is None else ""
        self.render()

    def _auto_refresh(self) -> None:
        self.refresh()
        self._refresh_after = self.after(self._refresh_ms, self._auto_refresh)

    def set_refresh_interval(self, minutes: int) -> None:
        """设置窗保存后调用：更新自动刷新周期并重启 after 链。"""
        self._refresh_ms = int(minutes) * 60_000
        if self._refresh_after:
            self.after_cancel(self._refresh_after)
        self._refresh_after = self.after(self._refresh_ms, self._auto_refresh)

    # ---------- 视图状态 ----------
    def _stats(self) -> DayStats | None:
        """当前粒度+游标下的聚合结果（本地 db 为主，官网 token 补历史缺失日期）。"""
        days = self._merged_days()
        if not days:
            return None
        if self.gran == "day":
            return _as_stats(days.get(self.cursor.isoformat()))
        if self.gran == "week":
            start = self.cursor - datetime.timedelta(days=self.cursor.weekday())
            return _as_stats(aggregate_week(days).get(start.isoformat()))
        return _as_stats(aggregate_month(days).get(self.cursor.strftime("%Y-%m")))

    def _merged_days(self) -> dict:
        """官网 token 优先（账户级口径），本地补缺（官网分页未覆盖的日期）。"""
        days = {}
        for d, e in (self._cloud_by_day or {}).items():
            t = e.get("tokens") if isinstance(e, dict) else None
            if t and any(t.get(k) for k in ("input", "output", "cache_read")):
                days[d] = DayStats(input=t.get("input", 0), output=t.get("output", 0),
                                   cache_read=t.get("cache_read", 0),
                                   cache_write=t.get("cache_write", 0),
                                   reasoning=t.get("reasoning", 0), cost=0,
                                   requests=t.get("requests", 0))
        for d, s in (self.by_day or {}).items():
            if d not in days:
                days[d] = s
        return days

    def _range_text(self) -> str:
        c = self.cursor
        if self.gran == "day":
            return f"{c.month}月{c.day}日(周{WEEKDAYS[c.weekday()]})"
        if self.gran == "week":
            start = c - datetime.timedelta(days=c.weekday())
            end = start + datetime.timedelta(days=6)
            return f"{start.month}月{start.day}日~{end.month}月{end.day}日"
        return f"{c.year}年{c.month}月"

    # ---------- 官网费用（以 opencode.ai 官网为准） ----------
    def _cloud_cost(self) -> float | None:
        """当前粒度+游标范围的官网费用合计；无数据返回 None。"""
        if not self._cloud_by_day:
            return None
        if self.gran == "day":
            e = self._cloud_by_day.get(self.cursor.isoformat())
            return e["total"] if e else None
        if self.gran == "week":
            start = self.cursor - datetime.timedelta(days=self.cursor.weekday())
            total, found = 0.0, False
            for i in range(7):
                e = self._cloud_by_day.get((start + datetime.timedelta(days=i)).isoformat())
                if e:
                    total += e["total"]
                    found = True
            return total if found else None
        prefix = self.cursor.strftime("%Y-%m")
        total, found = 0.0, False
        for d, e in self._cloud_by_day.items():
            if d.startswith(prefix):
                total += e["total"]
                found = True
        return total if found else None

    def sync_cloud(self) -> None:
        """后台拉官网费用（最近 2 个月）→ 缓存 → 重绘。"""
        if not self._cloud_enabled or not self._cloud_ws or not self._cloud_cookie:
            self._cloud_err = "未配置官网同步（设置 → 官网同步）"
            self.render()
            return

        def work():
            try:
                out = opencode_cloud.sync_month(self._cloud_ws, self._cloud_cookie,
                                                months=2)
                self.after(0, lambda: self._cloud_done(out["by_day"], None))
            except opencode_cloud.CloudError as e:
                self.after(0, lambda: self._cloud_done(None, str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _cloud_done(self, by_day, err) -> None:
        if by_day is not None:
            self._cloud_by_day = by_day
            self._cloud_sync_at = datetime.datetime.now().strftime("%H:%M")
            self._cloud_err = None
        else:
            self._cloud_err = err
        self.render()

    def set_cloud(self, args) -> None:
        """设置窗保存后调用：(workspace_id, cookie, enabled)。"""
        ws, cookie, enabled = args
        self._cloud_ws, self._cloud_cookie, self._cloud_enabled = ws, cookie, enabled
        if enabled and ws and cookie:
            self.sync_cloud()
        else:
            self.render()

    def _status_lines(self) -> tuple[str, str]:
        """状态栏两行：返回 (同步状态行, 提示/错误行)。"""
        if self.last_error:
            return (f"⟳ 已同步 {self._sync_time}",
                    f"⚠ {self.last_error}（右键 → 设置）")
        if self.by_day is None:
            return ("正在加载…", "")
        parts = [f"⟳ 已同步 {self._sync_time} · {self._refresh_ms // 60000}分钟自动"]
        hint = ""
        if self._cloud_enabled:
            if self._cloud_err:
                hint = f"⚠ {self._cloud_err}"
            elif self._cloud_sync_at:
                parts.append(f"官网 {self._cloud_sync_at}")
            else:
                hint = "官网未同步"
        return (" · ".join(parts), hint)

    def _nav(self, delta: int) -> None:
        c = self.cursor
        if self.gran == "day":
            self.cursor = c + datetime.timedelta(days=delta)
        elif self.gran == "week":
            self.cursor = c + datetime.timedelta(weeks=delta)
        else:
            y = c.year + (c.month - 1 + delta) // 12
            m = (c.month - 1 + delta) % 12 + 1
            self.cursor = c.replace(year=y, month=m)
        self.render()

    def _set_gran(self, gran: str) -> None:
        """切粒度并回到最新（今天的日 / 本周 / 本月）。"""
        self.gran = gran
        self.cursor = datetime.date.today()
        self.render()

    # ---------- 渲染 ----------
    def _fmt(self, n: int) -> str:
        """数字格式化：abbr 缩写（1.2K）/ plain 千分位（1,234）。"""
        if self._number_format == "plain":
            return f"{n:,}"
        return format_tokens(n)

    def set_number_format(self, fmt: str) -> None:
        """设置窗保存后调用：切换数字显示格式（abbr/plain）并重绘。"""
        self._number_format = fmt
        self.render()

    def render(self) -> None:
        C = self.C
        cv = self.canvas
        cv.delete("all")
        # 先测量实际内容，再确定高度，避免自适应增高后重复按 182 缩放。
        sx = self._sw / 250
        n_rows = sum(f in FIELD_LABELS for f in self._display_fields)
        show_hr = "hit_rate" in self._display_fields
        # 字号只随宽度变化；纵向空间不足时扩高窗口，不再压缩 UI。
        sc = sx
        fl = max(7, round(9 * sc))              # 标签字号（整数，Tk 拒绝浮点）
        f_num = ("Segoe UI", fl + 1, "normal")
        f_label = ("Segoe UI", fl, "normal")
        f_small = ("Segoe UI", max(7, fl - 1), "normal")
        pad = round(16 * sx)
        r = max(8, round(RADIUS * sc))
        sync_text, hint_text = self._status_lines()
        text_width = self._sw - 2 * pad

        def text_height(text):
            item = cv.create_text(0, 0, text=text, font=f_small, anchor="nw", width=text_width)
            bounds = cv.bbox(item)
            cv.delete(item)
            return bounds[3] - bounds[1] if bounds else 0

        sync_h = text_height(sync_text)
        hint_h = text_height(hint_text) if hint_text else 0
        footer_h = 12 + sync_h + (4 + hint_h if hint_text else 0) + 14
        body_h = 66 + max(0, n_rows - 1) * 28 + (27 if show_hr else 12)
        sy = sx
        h_req = min(MAX_H, max(MIN_H, round(body_h * sy + footer_h)))
        if self._sh != h_req:
            self._sh = h_req
            self.geometry(f"{self._sw}x{self._sh}")
            cv.configure(height=self._sh)
        # 阴影 + 卡片
        _round_rect(cv, round(6 * sx), round(8 * sy), self._sw - 2, self._sh - 2,
                    r, fill=C["shadow"], outline="")
        _round_rect(cv, 4, 4, self._sw - 4, self._sh - 4, r, fill=C["card"], outline="")
        # 顶部：◀ 范围 日 周 月 ▶（均衡两端对齐）
        y_top = round(28 * sy)
        cv.create_text(round(8 * sx), y_top, text="◀", font=f_label, fill=C["label"],
                       anchor="w", tags="nav_prev")
        cv.create_text(round(26 * sx), y_top, text=self._range_text(), font=f_label,
                       fill=C["main"], anchor="w", tags="range")
        for i, g in enumerate(("day", "week", "month")):
            active = self.gran == g
            cv.create_text(self._sw - round((64 - i * 22) * sx), y_top, text=GRAN_LABELS[g],
                           font=(f_label[0], f_label[1], "bold" if active else "normal"),
                           fill=C["main"] if active else C["label"],
                           anchor="e", tags=f"gran_{g}")
        cv.create_text(self._sw - round(8 * sx), y_top, text="▶", font=f_label,
                       fill=C["label"], anchor="e", tags="nav_next")
        # 分隔线（极浅）
        cv.create_line(pad, round(44 * sy), self._sw - pad, round(44 * sy),
                       fill=C["line"], width=1)
        # 指标行（官网计价口径，2026-08-13：默认 输入总/输出/命中率/费用，其余自定义）
        s = self._stats()
        rows = []
        for f in self._display_fields:
            label = FIELD_LABELS.get(f)
            if label is None:
                continue
            if f == "hit_rate":
                rows.append((label, "—" if s is None or s.hit_rate is None else f"{s.hit_rate:.1f}%"))
            elif f == "cost":
                cc = self._cloud_cost()
                rows.append((label, "—" if cc is None else f"${cc:.2f}"))
            elif f == "input_total":
                rows.append((label, self._fmt(s.input_total if s else 0)))
            elif f == "output":
                rows.append((label, self._fmt(s.output if s else 0)))
            elif f == "input_fresh":
                rows.append((label, self._fmt(s.input if s else 0)))
            elif f == "cache_read":
                rows.append((label, self._fmt(s.cache_read if s else 0)))
            elif f == "cache_write":
                rows.append((label, self._fmt(s.cache_write if s else 0)))
            elif f == "reasoning":
                rows.append((label, self._fmt(s.reasoning if s else 0)))
            elif f == "total":
                rows.append((label, self._fmt(s.total if s else 0)))
            elif f == "requests":
                rows.append((label, self._fmt(s.requests if s else 0)))
        for i, (label, text) in enumerate(rows):
            y = round((66 + i * 28) * sy)
            cv.create_text(pad, y, text=label, font=f_label, fill=C["label"],
                           anchor="w")
            cv.create_text(self._sw - pad, y, text=text, font=f_num, fill=C["main"],
                           anchor="e", tags=f"val_{label}")
        # 命中率进度条：浅灰轨道 + 三段式彩色填充（仅命中率显示时）
        if show_hr:
            bar_h = max(6, round(7 * sy))
            bar_y = round((66 + max(0, len(rows) - 1) * 28 + 20) * sy)
            _round_rect(cv, pad, bar_y, self._sw - pad, bar_y + bar_h,
                        max(3, round(4 * sc)), fill=C["track"], outline="", tags="track")
            if s is not None and s.hit_rate is not None:
                hr = s.hit_rate
                color = C["green"] if hr >= 70 else (C["orange"] if hr >= 30 else C["red"])
                bar_w = max(6, (self._sw - 2 * pad) * hr / 100)
                _round_rect(cv, pad, bar_y, pad + bar_w, bar_y + bar_h,
                            max(3, round(4 * sc)), fill=color, outline="", tags="bar")
        status_y = self._sh - footer_h + 12
        cv.create_text(pad, status_y, text=sync_text,
                       font=f_small, fill=C["status"], anchor="nw", width=text_width, tags="status")
        if hint_text:
            cv.create_text(pad, status_y + sync_h + 4, text=hint_text,
                           font=f_small,
                           fill=C["red"] if self.last_error else C["status"],
                           anchor="nw", width=text_width, tags="status2")
        # 右下角缩放手柄（grip 两点）
        gx, gy = self._sw - round(14 * sx), self._sh - round(14 * sy)
        cv.create_oval(gx, gy, gx + 4, gy + 4, fill=C["label"], outline="", tags="grip")
        cv.create_oval(gx - 7, gy + 7, gx - 3, gy + 11, fill=C["label"],
                       outline="", tags="grip")

    # ---------- 窗口行为 ----------
    def _no_activate(self) -> None:
        """WS_EX_NOACTIVATE：小窗创建/点击不抢焦点（不影响鼠标事件/拖拽）。"""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id()) or self.winfo_id()
            ex = ctypes.windll.user32.GetWindowLongPtrW(hwnd, -20)  # GWL_EXSTYLE
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, -20, ex | 0x08000000)
        except Exception:
            pass

    def _bind_drag(self) -> None:
        """手势：四角 8px 热区斜向缩放（Windows 风格），其余区域拖动。"""
        self._dx = self._dy = 0
        self._mode = "drag"          # drag / resize_se / resize_sw / resize_ne / resize_nw
        self._cursor = ""
        CURSORS = {"drag": "fleur", "resize_se": "size_nw_se", "resize_nw": "size_nw_se",
                   "resize_sw": "size_ne_sw", "resize_ne": "size_ne_sw"}
        EDGE = 8  # 四角热区边长

        def on_motion(e):
            w, h = self._sw, self._sh
            if self._lock_position:
                mode = "drag"  # 锁定只锁拖动，缩放保留
            elif e.x <= EDGE and e.y <= EDGE:
                mode = "resize_nw"
            elif e.x >= w - EDGE and e.y <= EDGE:
                mode = "resize_ne"
            elif e.x <= EDGE and e.y >= h - EDGE:
                mode = "resize_sw"
            elif e.x >= w - EDGE and e.y >= h - EDGE:
                mode = "resize_se"
            else:
                mode = "drag"
            if mode != self._mode:
                self._mode = mode
                try:
                    self.canvas.config(cursor=CURSORS[mode])
                except tk.TclError:
                    pass

        def on_press(e):
            self._dx, self._dy = e.x, e.y

        def on_drag(e):
            if self._mode == "drag":
                if self._lock_position:
                    return
                x, y = self.winfo_x() + e.x - self._dx, self.winfo_y() + e.y - self._dy
                self.geometry(f"+{x}+{y}")
                return
            # 四角斜向缩放（双向）：clamp 尺寸；左上/右上/左下角缩放时同步移动窗口（锚定对角）
            px = self.winfo_pointerx()
            py = self.winfo_pointery()
            x, y = self.winfo_x(), self.winfo_y()
            right = x + self._sw
            bottom = y + self._sh
            if self._mode == "resize_se":      # 锚左上
                self._sw = min(MAX_W, max(MIN_W, px - x))
                self._sh = min(MAX_H, max(MIN_H, py - y))
            elif self._mode == "resize_sw":    # 锚右上
                self._sw = min(MAX_W, max(MIN_W, right - px))
                self._sh = min(MAX_H, max(MIN_H, py - y))
                x = right - self._sw
            elif self._mode == "resize_ne":    # 锚左下
                self._sw = min(MAX_W, max(MIN_W, px - x))
                self._sh = min(MAX_H, max(MIN_H, bottom - py))
                y = bottom - self._sh
            elif self._mode == "resize_nw":    # 锚右下
                self._sw = min(MAX_W, max(MIN_W, right - px))
                self._sh = min(MAX_H, max(MIN_H, bottom - py))
                x, y = right - self._sw, bottom - self._sh
            self.geometry(f"{self._sw}x{self._sh}+{x}+{y}")
            self.canvas.config(width=self._sw, height=self._sh)
            self.render()

        def on_release(_e):
            if self._mode != "drag":  # 缩放结束：记忆尺寸与位置
                cfg = config.load_config()
                cfg["window_size"] = [self._sw, self._sh]
                cfg["window_pos"] = [self.winfo_x(), self.winfo_y()]
                config.save_config(cfg)
            self._mode = "drag"

        self.canvas.bind("<Motion>", on_motion)
        self.canvas.bind("<ButtonPress-1>", on_press)
        self.canvas.bind("<B1-Motion>", on_drag)
        self.canvas.bind("<ButtonRelease-1>", on_release)
        self.canvas.bind("<Double-Button-1>", lambda e: self._open_calendar())  # 双击开日历

    def set_lock_position(self, lock: bool) -> None:
        """设置窗保存后调用：锁定/解锁拖动。"""
        self._lock_position = bool(lock)

    def set_display_fields(self, fields: list) -> None:
        """设置窗保存后调用：更新显示内容（输入/输出/命中率/推理/成本）并重绘。"""
        self._display_fields = list(fields) or list(DEFAULT_FIELDS)
        self.render()

    def set_click_through(self, on: bool) -> None:
        """鼠标穿透（WS_EX_TRANSPARENT）：点击不拦截，配合置顶/托盘使用。"""
        self._click_through = bool(on)
        try:
            hwnd = _root_hwnd(self)
            ex = ctypes.windll.user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            ex = (ex | 0x20) if on else (ex & ~0x20)  # WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex)
        except Exception:
            pass

    def _bind_actions(self) -> None:
        cv = self.canvas
        cv.tag_bind("nav_prev", "<Button-1>", lambda e: self._nav(-1))
        cv.tag_bind("nav_next", "<Button-1>", lambda e: self._nav(1))
        for g in ("day", "week", "month"):
            cv.tag_bind(f"gran_{g}", "<Button-1>", lambda e, x=g: self._set_gran(x))
        cv.tag_bind("range", "<Button-1>", lambda e: self._open_calendar())

    def _bind_menu(self) -> None:
        # Windows 上 tk.Menu 是系统原生绘制，bg/fg 通常不生效；仍按主题设置（X11 等平台生效）
        m = tk.Menu(self, tearoff=0, bg=self.C["card"], fg=self.C["main"],
                    activebackground=self.C["btn_hover"],
                    activeforeground=self.C["main"])
        m.add_command(label="⟳ 刷新", command=self.refresh)
        m.add_command(label="☁ 同步官网费用", command=self.sync_cloud)
        self._topmost_var = tk.BooleanVar(value=bool(self.attributes("-topmost")))  # 与窗口当前置顶状态同步
        m.add_checkbutton(label="📌 置顶", variable=self._topmost_var,
                          command=self._toggle_topmost)
        self._click_var = tk.BooleanVar(value=self._click_through)
        m.add_checkbutton(label="🖱 鼠标穿透（Ctrl+Alt+Shift+T 恢复）",
                          variable=self._click_var, command=self._toggle_click)
        m.add_command(label="⚙ 设置", command=self._open_settings)
        m.add_separator()
        m.add_command(label="ℹ 关于", command=self._about)
        m.add_command(label="✕ 退出", command=self._exit)
        self._menu = m

        def popup(e):
            try:
                m.tk_popup(e.x_root, e.y_root)
            finally:
                m.grab_release()

        self.canvas.bind("<Button-3>", popup)

    def _toggle_topmost(self) -> None:
        """切换置顶 + 任务栏可见性。

        置顶开：TOOLWINDOW 隐藏任务栏按钮（小窗不占任务栏）；
        置顶关：清 TOOLWINDOW + 加 APPWINDOW，hide/show 强制 shell 重评估，
        任务栏出现按钮——即使被全屏应用盖住也能从任务栏找回。
        """
        on = self._topmost_var.get()
        self.attributes("-topmost", on)
        _set_taskbar_visible(_root_hwnd(self), show=not on)

    def _toggle_click(self) -> None:
        """右键菜单切换鼠标穿透（开启后需用热键 Ctrl+Alt+Shift+T 恢复）。"""
        self.set_click_through(self._click_var.get())

    # ---------- 全局热键（防"鼠标穿透后无法恢复"的死锁） ----------
    # Ctrl+Alt+Shift+T = 切换鼠标穿透；Ctrl+Alt+Shift+S = 打开设置
    def _register_hotkeys(self) -> None:
        try:
            user32 = ctypes.windll.user32
            hwnd = _root_hwnd(self)
            user32.RegisterHotKey(hwnd, 1, 0x1 | 0x2 | 0x4, ord("T"))  # ALT|CTRL|SHIFT
            user32.RegisterHotKey(hwnd, 2, 0x1 | 0x2 | 0x4, ord("S"))
            self.after(200, self._poll_hotkeys)
        except Exception:
            pass

    def _poll_hotkeys(self) -> None:
        """轮询 WM_HOTKEY（PM_NOREMOVE 只查不取，不干扰 Tk 消息队列）。"""
        try:
            user32 = ctypes.windll.user32

            class MSG(ctypes.Structure):
                _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                            ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_size_t),
                            ("time", ctypes.c_ulong), ("pt", ctypes.c_long * 2)]

            WM_HOTKEY = 0x0312
            msg = MSG()
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0x0001):  # PM_NOREMOVE
                if msg.message == WM_HOTKEY:
                    if msg.wParam == 1:
                        self._click_var.set(not self._click_through)
                        self._toggle_click()
                    elif msg.wParam == 2:
                        self._open_settings()
                break  # 每轮只处理一条，避免死循环
        except Exception:
            pass
        self.after(200, self._poll_hotkeys)

    def _exit(self) -> None:
        cfg = config.load_config()
        cfg["window_pos"] = [self.winfo_x(), self.winfo_y()]  # 记忆位置
        cfg["window_size"] = [self._sw, self._sh]               # 记忆尺寸
        config.save_config(cfg)
        try:
            self._tray.destroy()
        except Exception:
            pass
        self.destroy()

    # ---------- 系统托盘（关闭/找回入口） ----------
    def _init_tray(self) -> None:
        try:
            hwnd = _root_hwnd(self)
            self._tray = TrayIcon(hwnd, icon_name="assets/app.ico")
            self._tray.on_menu = self._show_tray_menu
            self._tray.on_show = self._show_from_tray
        except Exception:
            self._tray = None  # 托盘失败不影响主功能

    def _show_from_tray(self) -> None:
        """托盘双击：显示并置顶主窗。"""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
        except Exception:
            pass

    def _show_tray_menu(self) -> None:
        """托盘右键菜单：显示 / 设置 / 同步官网 / 退出。"""
        try:
            m = tk.Menu(self, tearoff=0)
            m.add_command(label="显示窗口", command=self._show_from_tray)
            m.add_command(label="⚙ 设置", command=self._open_settings)
            m.add_command(label="☁ 同步官网费用", command=self.sync_cloud)
            m.add_separator()
            m.add_command(label="✕ 退出", command=self._exit)
            pt = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            m.tk_popup(pt.x, pt.y)
            m.grab_release()
        except Exception:
            pass

    def _open_settings(self) -> None:
        Settings(self, on_saved=self.refresh)  # 保存后立即按新配置刷新

    def _about(self) -> None:
        """自绘 Apple 风格关于卡片：无边框圆角 + 半透明 + 蓝色确定按钮，跟随主题。

        参考 settings.py 的窗口样式（overrideredirect + transparentcolor 抠角）。
        """
        if getattr(self, "_about_win", None) and self._about_win.winfo_exists():
            return  # 已打开则复用（防重复堆叠）
        C = self.C
        W, H = 300, 180
        win = tk.Toplevel(self)
        self._about_win = win
        win.overrideredirect(True)
        win.configure(bg=KEY)
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.92)
        win.attributes("-transparentcolor", KEY)
        cv = tk.Canvas(win, width=W, height=H, bg=KEY, highlightthickness=0, bd=0)
        cv.pack()
        _round_rect(cv, 4, 4, W - 4, H - 4, 16, fill=C["card"], outline="")
        cv.create_text(W / 2, 34, text="OpenCodeGO Token Watcher",
                       font=("Segoe UI", 12, "bold"), fill=C["main"])
        for i, t in enumerate(("实时监测 opencode / OpenChamber 的 token 用量",
                               "数据源：本地 opencode.db（只读）",
                               "版本：0.1（阶段 4）")):
            cv.create_text(W / 2, 68 + i * 20, text=t,
                           font=("Segoe UI", 9), fill=C["label"])
        tk.Button(win, text="确定", command=win.destroy,
                  font=("Segoe UI", 9, "bold"), bg=C["today"], fg="#FFFFFF",
                  activebackground=C["btn_hover"], activeforeground="#FFFFFF",
                  relief="flat", bd=0, padx=20, pady=5, cursor="hand2"
                  ).place(x=(W - 80) / 2, y=H - 52, width=80, height=30)
        # 居中于主窗
        win.update_idletasks()
        x = max(0, self.winfo_rootx() + (self.winfo_width() - W) // 2)
        y = max(0, self.winfo_rooty() + (self.winfo_height() - H) // 2)
        win.geometry(f"+{x}+{y}")

    # ---------- 日历弹窗 ----------
    def _open_calendar(self) -> None:
        """toggle：开着则关闭，关着则打开。"""
        cal = getattr(self, "_cal", None)
        if cal and cal.winfo_exists():
            cal.destroy()
            self._cal = None
            return
        self._cal = _Calendar(self, self.cursor, self._pick_date)

    def _pick_date(self, d: datetime.date) -> None:
        self.gran = "day"
        self.cursor = d
        self.render()


class _Calendar(tk.Toplevel):
    """Apple 风格月历：与主窗同款白卡片 / 圆角 / 半透明 / 配色。

    标题 ◀ 2026年8月 ▶（可翻月），周一起算 42 格，今天苹果蓝圆底白字。
    """
    CW, CH = 244, 208
    CELL_W, CELL_H = 32, 22
    PAD = 16
    TOP = 40   # 标题行 y
    HEAD = 58  # 表头行 y

    def __init__(self, master, anchor: datetime.date, on_pick):
        super().__init__(master)
        self._on_pick = on_pick
        self._view = anchor.replace(day=1)
        self.overrideredirect(True)
        self.configure(bg=KEY)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.78)
        self.attributes("-transparentcolor", KEY)
        self.canvas = tk.Canvas(self, width=self.CW, height=self.CH, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._draw()
        # 定位在主窗下方（放不下则上方）
        self.update_idletasks()
        x = master.winfo_rootx() + 8
        y = master.winfo_rooty() + master.winfo_height() + 4
        if y + self.CH > self.winfo_screenheight():
            y = master.winfo_rooty() - self.CH - 4
        self.geometry(f"+{x}+{y}")

    def _draw(self) -> None:
        C = self.master.C  # 主题配色（master 是 UsageWindow）
        cv = self.canvas
        cv.delete("all")
        _round_rect(cv, 4, 4, self.CW - 4, self.CH - 4, 14, fill=C["card"], outline="")
        # 标题：◀ 2026年8月 ▶
        cv.create_text(26, self.TOP, text="◀", font=FONT_LABEL, fill=C["label"],
                       anchor="w", tags="cal_prev")
        cv.create_text(self.CW - 26, self.TOP, text="▶", font=FONT_LABEL,
                       fill=C["label"], anchor="e", tags="cal_next")
        cv.create_text(self.CW / 2, self.TOP, text=f"{self._view.year}年{self._view.month}月",
                       font=("Segoe UI", 10, "bold"), fill=C["main"], tags="cal_title")
        cv.create_line(self.PAD, self.TOP + 12, self.CW - self.PAD, self.TOP + 12,
                       fill=C["line"], width=1)
        # 表头（周一起）
        for i, d in enumerate("一二三四五六日"):
            cv.create_text(self.PAD + i * self.CELL_W + 16, self.HEAD,
                           text=d, font=("Segoe UI", 8), fill=C["label"])
        # 42 格日期
        first = self._view.replace(day=1)
        start = first - datetime.timedelta(days=first.weekday())
        today = datetime.date.today()
        for i in range(42):
            d = start + datetime.timedelta(days=i)
            cx = self.PAD + (i % 7) * self.CELL_W + 16
            cy = self.HEAD + 12 + (i // 7) * self.CELL_H + 13
            if d == today:
                _round_rect(cv, cx - 11, cy - 10, cx + 11, cy + 10, 10,
                            fill=C["today"], outline="", tags=f"cal_daybg_{d.isoformat()}")
                fg = "#FFFFFF"
            elif d.month == self._view.month:
                fg = C["main"]
            else:
                fg = C["muted"]
            cv.create_text(cx, cy, text=str(d.day), font=("Segoe UI", 10),
                           fill=fg, tags=f"cal_day_{d.isoformat()}")
        cv.tag_bind("cal_prev", "<Button-1>", lambda e: self._shift(-1))
        cv.tag_bind("cal_next", "<Button-1>", lambda e: self._shift(1))
        for i in range(42):
            d = start + datetime.timedelta(days=i)
            cv.tag_bind(f"cal_day_{d.isoformat()}", "<Button-1>",
                        lambda e, x=d: self._pick(x))

    def _shift(self, delta: int) -> None:
        y = self._view.year + (self._view.month - 1 + delta) // 12
        m = (self._view.month - 1 + delta) % 12 + 1
        self._view = self._view.replace(year=y, month=m)
        self._draw()

    def _pick(self, d: datetime.date) -> None:
        self._on_pick(d)
        self.destroy()

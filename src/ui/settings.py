"""设置窗：macOS System Settings 风格（分组卡片 + 整页滚动 + 全自绘控件）。

节：外观 / 行为 / 显示内容 / 官网同步 / 关于 / 高级设置（折叠，含连接）。
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog

from src import chrome_cdp, config, db_reader, theme
from src.opencode_cloud import (CloudError, fetch_workspace_id, month_costs,
                                start_oauth_login)

W, H = 400, 720
KEY = theme.KEY
FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_SECTION = ("Segoe UI", 9, "bold")
FONT_LABEL = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
HELP_TEXT = (
    "opencode.db 是什么？\n\n"
    "OpenChamber 与 opencode CLI 共用的本地数据库，\n"
    "保存全部会话与 token 用量。\n\n"
    "默认位置：\n%USERPROFILE%\\.local\\share\\opencode\\opencode.db\n\n"
    "一般无需手动指定，程序会自动探测；\n探测不到或想换数据源时再手动选择。"
)
CLOUD_HELP = (
    "官网费用同步是什么？\n\n"
    "小窗的 token 数量读本地数据库（准确）；\n"
    "费用（$）以 opencode.ai 官网账单为准。\n\n"
    "如何获取 cookie：\n"
    "1. 浏览器登录 opencode.ai\n"
    "2. 按 F12 打开开发者工具 → Network 面板\n"
    "3. 刷新页面，点击任意 opencode.ai 请求\n"
    "4. 在 Request Headers 里复制 Cookie 整行\n"
    "5. 粘贴到上方输入框（一年内有效）\n\n"
    "workspace ID：网址 /workspace/ 后面那段（wrk_ 开头）。"
)


def _round_rect(cv, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


# ---------- Apple 风格控件（全部自绘） ----------
class AppleControl(tk.Canvas):
    """自绘选择控件：check（方框对勾）/ radio（蓝底白字药丸）。"""

    def __init__(self, master, text, variable, colors, font, w=180, h=24,
                 command=None, kind="check", bg=None, value=None):
        super().__init__(master, width=w, height=h, bg=bg or colors["group"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._var = text, variable
        self._colors, self._font, self._command = colors, font, command
        self._kind = kind
        self._value = value  # radio 时比较用（var.get() == value 判定选中）
        self._draw()
        self.bind("<Button-1>", self._toggle)
        self._var.trace_add("write", lambda *a: self._draw())

    def _draw(self):
        self.delete("all")
        c = self._colors
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        if self._kind == "radio" and self._value is not None:
            on = self._var.get() == self._value  # 值比较（修复 StringVar 非空恒选中）
        else:
            on = bool(self._var.get())
        box = (2, 5, 18, 21)
        if self._kind == "check":
            if on:
                _round_rect(self, *box, 4, fill=c["today"], outline="")
                self.create_line(6, 13, 9.5, 16.5, 15, 9, fill="#FFFFFF",
                                 width=1.6, capstyle="round", joinstyle="round")
            else:
                _round_rect(self, *box, 4, fill=c["group"], outline=c["muted"], width=1.2)
            self.create_text(26, 13, text=self._text, font=self._font,
                             fill=c["main"], anchor="w")
        else:  # radio 药丸：选中蓝底白字，未选中描边灰字
            if on:
                _round_rect(self, 0, 0, w - 1, h - 1, h // 2,
                            fill=c["today"], outline="")
                self.create_text(w / 2, h / 2, text=self._text, font=self._font,
                                 fill="#FFFFFF")
            else:
                _round_rect(self, 0, 0, w - 1, h - 1, h // 2,
                            fill=c["group"], outline=c["muted"], width=1)
                self.create_text(w / 2, h / 2, text=self._text, font=self._font,
                                 fill=c["main"])

    def _toggle(self, _e=None):
        if self._kind == "radio" and self._value is not None:
            if self._var.get() != self._value:
                self._var.set(self._value)  # 设值（触发 trace 重绘）
                if self._command:
                    self._command()
            return
        self._var.set(not bool(self._var.get()))
        self._draw()
        if self._command:
            self._command()


class AppleEntry(tk.Canvas):
    """圆角边框输入框（macOS 风）：边框 1px，聚焦变蓝；长文本自动横向滚动到末尾。"""

    def __init__(self, master, textvariable, colors, font=FONT_LABEL,
                 width=200, height=26, show=None, **kw):
        super().__init__(master, width=width, height=height, bg=colors["group"],
                         highlightthickness=0, bd=0)
        self._colors = colors
        self._r = 6
        self._entry = tk.Entry(self, textvariable=textvariable, font=font,
                               relief="flat", bd=0, show=show,
                               bg=colors["entry_bg"], fg=colors["main"],
                               insertbackground=colors["main"],
                               highlightthickness=0, **kw)
        self._entry.place(x=8, y=4, width=width - 16, height=height - 8)
        self._draw("normal")
        self._entry.bind("<FocusIn>", lambda e: self._draw("focus"))
        self._entry.bind("<FocusOut>", lambda e: self._draw("normal"))
        # 长文本（如 wrk_...）自动横向滚动到末尾，不溢出
        try:
            textvariable.trace_add("write", lambda *a: self._entry.xview_moveto(1.0))
        except Exception:
            pass
        self.entry = self._entry  # 暴露内部 entry

    def _draw(self, state):
        self.delete("all")
        c = self._colors
        edge = c["today"] if state == "focus" else c["entry_border"]
        _round_rect(self, 1, 1, self.winfo_reqwidth() - 1,
                    self.winfo_reqheight() - 1, self._r,
                    fill=c["entry_bg"], outline=edge, width=1)


class AppleButton(tk.Canvas):
    """圆角填充按钮：primary（蓝底白字）/ normal（灰底深字），悬停变色。"""

    def __init__(self, master, text, command, colors, font=FONT_LABEL,
                 width=70, height=26, primary=False):
        super().__init__(master, width=width, height=height, bg=colors["group"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._text, self._cmd = text, command
        self._colors, self._font, self._primary = colors, font, primary
        self._draw("normal")
        self.bind("<Enter>", lambda e: self._draw("hover"))
        self.bind("<Leave>", lambda e: self._draw("normal"))
        self.bind("<Button-1>", lambda e: self._cmd())

    def _draw(self, state):
        self.delete("all")
        c = self._colors
        if self._primary:
            fill = c["today"] if state == "normal" else c["btn_hover"]
            fg = "#FFFFFF"
        else:
            fill = c["btn"] if state == "normal" else c["btn_hover"]
            fg = c["main"]
        _round_rect(self, 1, 1, self.winfo_reqwidth() - 1,
                    self.winfo_reqheight() - 1, 7, fill=fill, outline="")
        self.create_text(self.winfo_reqwidth() / 2, self.winfo_reqheight() / 2,
                         text=self._text, font=self._font, fill=fg)


class AppleCombo(tk.Canvas):
    """下拉选择（自绘）：点击弹选项列表，选后回调。"""

    def __init__(self, master, values, variable, command, colors,
                 font=FONT_LABEL, width=120, height=26, bg=None):
        super().__init__(master, width=width, height=height, bg=bg or colors["group"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self._values, self._var = values, variable
        self._cmd, self._colors, self._font = command, colors, font
        self._draw()
        self.bind("<Button-1>", self._open)

    def _draw(self):
        self.delete("all")
        c = self._colors
        _round_rect(self, 1, 1, self.winfo_reqwidth() - 1,
                    self.winfo_reqheight() - 1, 6,
                    fill=c["combo_bg"], outline=c["entry_border"], width=1)
        self.create_text(10, self.winfo_reqheight() / 2,
                         text=str(self._var.get()), font=self._font,
                         fill=c["main"], anchor="w")
        self.create_text(self.winfo_reqwidth() - 14, self.winfo_reqheight() / 2,
                         text="▾", font=("Segoe UI", 8), fill=c["label"], anchor="e")

    def _open(self, _e=None):
        c = self._colors
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.configure(bg=KEY)
        top.attributes("-topmost", True)
        top.attributes("-transparentcolor", KEY)
        n = len(self._values)
        h = n * 28 + 8
        cv = tk.Canvas(top, width=self.winfo_reqwidth(), height=h, bg=KEY,
                       highlightthickness=0, bd=0)
        cv.pack()
        _round_rect(cv, 2, 2, self.winfo_reqwidth() - 2, h - 2, 10,
                    fill=c["group"], outline=c["entry_border"], width=1)
        for i, v in enumerate(self._values):
            y = 8 + i * 28
            if i:
                cv.create_line(12, y - 2, self.winfo_reqwidth() - 12, y - 2,
                               fill=c["group_line"])
            tag = f"opt{i}"
            cv.create_text(14, y + 14, text=str(v), font=self._font,
                           fill=c["main"], anchor="w", tags=tag)
            cv.tag_bind(tag, "<Button-1>",
                        lambda e, val=v: self._pick(val, top))
        top.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_reqheight() + 2
        if y + h > self.winfo_screenheight():
            y = self.winfo_rooty() - h - 2
        top.geometry(f"+{x}+{y}")

    def _pick(self, val, top):
        self._var.set(val)
        self._draw()
        top.destroy()
        if self._cmd:
            self._cmd(val)


class AlphaSlider(tk.Canvas):
    """Apple 风格透明度滑块：点击跳转 / 拖动 / 滚轮微调。轨道底色用卡片色（不透明）。"""
    KNOB = 16
    TRACK_H = 5

    def __init__(self, master, variable, command, from_=0.50, to=0.95,
                 resolution=0.01, colors=None, width=200, height=26, bg=None):
        super().__init__(master, width=width, height=height,
                         bg=bg or colors.get("group", KEY),
                         highlightthickness=0, bd=0)
        self._var, self._command = variable, command
        self._lo, self._hi, self._res = from_, to, resolution
        self._colors = colors or {}
        self._pressed = False
        self._x0 = self.KNOB // 2 + 1
        self._x1 = width - self.KNOB // 2 - 1
        self._redraw()
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<MouseWheel>", self._on_wheel)

    def _redraw(self):
        self.delete("all")
        c = self._colors
        v = float(self._var.get())
        frac = (v - self._lo) / (self._hi - self._lo)
        x = self._x0 + frac * (self._x1 - self._x0)
        y = self.winfo_reqheight() // 2
        track = c.get("track", "#E5E5E8")
        self.create_line(self._x0, y, self._x1, y, width=self.TRACK_H,
                         fill=track, capstyle="round")
        self.create_line(self._x0, y, x, y, width=self.TRACK_H,
                         fill=c.get("today", "#0071E3"), capstyle="round")
        r = self.KNOB // 2
        self.create_oval(x - r, y - r, x + r, y + r,
                         fill=c.get("knob", "#FFFFFF"),
                         outline=c.get("knob_edge", "#B0B0B8"), width=1)

    def _set_frac(self, frac):
        v = self._lo + frac * (self._hi - self._lo)
        v = round(v / self._res) * self._res
        v = max(self._lo, min(v, self._hi))
        self._var.set(v)
        self._redraw()
        if self._command:
            self._command(v)

    def _on_press(self, e):
        self._pressed = True
        self.focus_set()
        self.grab_set()
        self._set_frac((e.x - self._x0) / (self._x1 - self._x0))

    def _on_drag(self, e):
        if self._pressed:
            self._set_frac((e.x - self._x0) / (self._x1 - self._x0))

    def _on_release(self, _e):
        self._pressed = False
        try:
            self.grab_release()
        except tk.TclError:
            pass

    def _on_wheel(self, e):
        v = float(self._var.get()) + (1 if e.delta > 0 else -1) * self._res
        v = max(self._lo, min(v, self._hi))
        self._var.set(v)
        self._redraw()
        if self._command:
            self._command(v)


# ---------- 设置窗主体 ----------
class Settings(tk.Toplevel):
    """macOS System Settings 风格设置窗：分组卡片 + 整页滚动。"""

    GROUP_X = 16
    GROUP_W = W - 32          # 卡片宽 368
    ROW_H = 44                # 组内行高（macOS 标准）
    ROW_LABEL_X = GROUP_X + 16

    def __init__(self, master, on_saved=None):
        super().__init__(master)
        self._on_saved = on_saved
        self._cfg = config.load_config()
        self.C = theme.get_palette(self._cfg.get("theme", "system"))
        self.overrideredirect(True)
        self.configure(bg=KEY)
        self.attributes("-topmost", True)
        self.attributes("-alpha", float(self.master.attributes("-alpha")))  # 与主窗同步
        self.attributes("-transparentcolor", KEY)
        self._init_vars()
        self._build_frame()
        self._bind_drag()
        self._place()

    # ---------- 变量 ----------
    def _init_vars(self):
        self.var_path = tk.StringVar(value=self._cfg.get("db_path") or "")
        self.var_auto = tk.BooleanVar(value=bool(self._cfg.get("autostart")))
        self.var_theme = tk.StringVar(value=self._cfg.get("theme", "system"))
        self.var_alpha = tk.DoubleVar(value=float(self._cfg.get("window_alpha", 0.78)))
        self.var_refresh = tk.IntVar(value=int(self._cfg.get("refresh_interval", 1)))
        self.var_format = tk.StringVar(value=self._cfg.get("number_format", "abbr"))
        self.var_topmost = tk.BooleanVar(value=bool(self._cfg.get("topmost_on_start", True)))
        self.var_lock = tk.BooleanVar(value=bool(self._cfg.get("lock_position", False)))
        self.var_click = tk.BooleanVar(value=bool(self._cfg.get("click_through", False)))
        self.var_ws = tk.StringVar(value=self._cfg.get("cloud_workspace_id") or "")
        self.var_cookie = tk.StringVar(value=self._cfg.get("cloud_cookie") or "")
        self.var_cloud_on = tk.BooleanVar(value=bool(self._cfg.get("cloud_enabled", False)))
        self.var_adv = tk.BooleanVar(value=False)  # 高级设置折叠
        self.var_fields = {f: tk.BooleanVar(value=f in self._cfg.get(
            "display_fields", ["input_total", "output", "hit_rate", "cost"]))
            for f in ("input_total", "output", "hit_rate", "cost",
                      "input_fresh", "cache_read", "cache_write",
                      "reasoning", "total", "requests")}

    # ---------- 构建 ----------
    def _build_frame(self):
        if hasattr(self, "canvas"):
            self.canvas.destroy()
        self.canvas = tk.Canvas(self, width=W, height=H, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        # 窗口圆角底 + 标题
        _round_rect(self.canvas, 4, 4, W - 4, H - 4, 16,
                    fill=self.C["win_bg"], outline="")
        tk.Label(self.canvas, text="设置", font=FONT_TITLE, bg=self.C["win_bg"],
                 fg=self.C["main"]).place(x=W / 2 - 20, y=12, width=40, height=24)
        self._lbl_close = tk.Label(self.canvas, text="✕", font=FONT_LABEL,
                                    bg=self.C["win_bg"], fg=self.C["label"],
                                    cursor="hand2")
        self._lbl_close.place(x=W - 34, y=14, width=20)
        self._lbl_close.bind("<Button-1>", lambda e: self.destroy())
        self.canvas.create_line(18, 40, W - 18, 40, fill=self.C["group_line"], width=1)
        # 滚动区（y 44 ~ 保存按钮上方）
        self.scroll = tk.Canvas(self, bg=self.C["win_bg"], highlightthickness=0, bd=0)
        self.scroll.place(x=0, y=44, width=W, height=H - 44 - 62)
        self.content = tk.Frame(self.scroll, bg=self.C["win_bg"])
        self._win = self.scroll.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>",
                          lambda e: self.scroll.configure(scrollregion=self.scroll.bbox("all")))
        self.scroll.bind("<MouseWheel>", self._on_scroll)
        # 子控件（卡片/输入框等）会吃掉滚轮事件 → 全局绑定
        self.bind_all("<MouseWheel>", self._on_scroll)
        self.bind_all("<Button-4>", self._on_scroll)   # Linux 上滚
        self.bind_all("<Button-5>", self._on_scroll)   # Linux 下滚
        self.scroll.configure(width=W)  # 固定内容宽度
        self._build_groups()
        # 保存/取消（固定底部）
        self.btn_save = AppleButton(self, "保存", self._save, self.C,
                                    font=("Segoe UI", 9, "bold"),
                                    width=62, height=28, primary=True)
        self.btn_save.place(x=W - 18 - 62, y=H - 48)
        self.btn_cancel = AppleButton(self, "取消", self.destroy, self.C,
                                      width=62, height=28)
        self.btn_cancel.place(x=W - 18 - 62 - 70, y=H - 48)

    def _group(self, y, title):
        """在 content 中建一组卡片，返回 (card_canvas, 行起点 y, 卡片底 y)。"""
        c = self.C
        card = tk.Canvas(self.content, width=self.GROUP_W, height=40,
                         bg=self.C["win_bg"], highlightthickness=0, bd=0)
        card.place(x=self.GROUP_X, y=y + 26)
        _round_rect(card, 1, 1, self.GROUP_W - 1, 39, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        tk.Label(self.content, text=title, font=FONT_SECTION, bg=self.C["win_bg"],
                 fg=c["label"]).place(x=self.ROW_LABEL_X, y=y)
        return card

    def _row_line(self, card, y):
        card.create_line(16, y, self.GROUP_W - 16, y,
                         fill=self.C["group_line"], width=1)

    def _check(self, parent, x, y, text, var, w=170):
        return AppleControl(parent, text, var, self.C, FONT_LABEL, w=w)

    def _label(self, parent, x, y, text, color=None, font=FONT_LABEL):
        # bg 用卡片填充色（group），与卡片同色融入（不能用 parent["bg"]=win_bg）
        tk.Label(parent, text=text, font=font, bg=self.C["group"],
                 fg=color or self.C["main"]).place(x=x, y=y)


    def _build_groups(self):
        c = self.C
        y = 10

        # ---- 外观 ----
        g = self._group(y, "外观")
        rh = self.ROW_H
        y += 40
        for i, (val, text) in enumerate((("system", "跟随系统"),
                                         ("light", "浅色"), ("dark", "深色"))):
            r = AppleControl(g, text, self.var_theme, self.C, FONT_LABEL,
                             w=104, h=26, kind="radio", value=val,
                             command=lambda: self._apply_theme())
            r.place(x=16 + i * 110, y=9)
        self._row_line(g, rh)
        self._label(g, 16, rh + 10, "透明度", color=c["label"])
        self.scale = AlphaSlider(g, variable=self.var_alpha,
                                 command=self._preview_alpha,
                                 colors={"track": c["track"], "today": c["today"],
                                         "knob": "#FFFFFF" if self.C is theme.LIGHT else "#F5F5F7",
                                         "knob_edge": "#B0B0B8" if self.C is theme.LIGHT else "#5A5A5E",
                                         "group": c["group"]},
                                 width=self.GROUP_W - 16 - 56 - 66, bg=c["group"])
        self.scale.place(x=76, y=rh + 8)
        self.lbl_alpha = tk.Label(g, text=f"{int(round(float(self.var_alpha.get()) * 100))}%",
                                  font=FONT_LABEL, fg=c["main"], bg=c["group"])
        self.lbl_alpha.place(x=self.GROUP_W - 16 - 56, y=rh + 10)
        g.configure(height=rh * 2)
        _round_rect(g, 1, 1, self.GROUP_W - 1, rh * 2 - 1, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        y += rh * 2 + 26

        # ---- 行为 ----
        g = self._group(y, "行为")
        y += 40
        self._label(g, 16, 12, "刷新间隔", color=c["label"])
        self.btn_minus = AppleButton(g, "−", lambda: self._step_refresh(-1), self.C,
                                     width=28, height=24)
        self.btn_minus.place(x=120, y=10)
        self.lbl_refresh = tk.Label(g, text=f"{self.var_refresh.get()} 分钟",
                                    font=FONT_LABEL, fg=c["main"], bg=c["group"])
        self.lbl_refresh.place(x=156, y=14)
        self.btn_plus = AppleButton(g, "＋", lambda: self._step_refresh(1), self.C,
                                    width=28, height=24)
        self.btn_plus.place(x=230, y=10)
        self._row_line(g, rh)
        self._label(g, 16, rh + 12, "数字格式", color=c["label"])
        for i, (val, text) in enumerate((("abbr", "缩写"), ("plain", "完整"))):
            r = AppleControl(g, text, self.var_format, self.C, FONT_LABEL,
                             w=70, h=26, kind="radio", value=val)
            r.place(x=120 + i * 90, y=rh + 9)
        for i, (text, var) in enumerate((("启动时置顶", self.var_topmost),
                                         ("锁定窗口位置", self.var_lock),
                                         ("开机自动启动", self.var_auto),
                                         ("鼠标穿透（Ctrl+Alt+Shift+T 恢复）", self.var_click))):
            yrow = (i + 2) * rh
            self._row_line(g, yrow)
            self._check(g, 16, yrow + 10, text, var).place(x=16, y=yrow + 10)
        g.configure(height=rh * 6)
        _round_rect(g, 1, 1, self.GROUP_W - 1, rh * 6 - 1, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        y += rh * 6 + 26

        # ---- 显示内容 ----
        g = self._group(y, "显示内容")
        y += 40
        fields = (("input_total", "输入（总）"), ("output", "输出"),
                  ("hit_rate", "命中率"), ("cost", "费用（$）"),
                  ("input_fresh", "新鲜输入"), ("cache_read", "缓存读"),
                  ("cache_write", "缓存写"), ("reasoning", "推理"),
                  ("total", "总 token"), ("requests", "请求次数"))
        for i, (f, text) in enumerate(fields):
            col, row = i % 2, i // 2
            self._check(g, 16 + col * 180, row * rh + 12, text,
                        self.var_fields[f]).place(x=16 + col * 180, y=row * rh + 12)
        g.configure(height=rh * 5)
        _round_rect(g, 1, 1, self.GROUP_W - 1, rh * 5 - 1, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        y += rh * 5 + 26

        # ---- 官网同步（label 行 + entry 全宽横向滚动，不溢出） ----
        g = self._group(y, "官网同步")
        y += 40
        self._label(g, 16, 12, "Workspace ID", color=c["label"])
        self.entry_ws = AppleEntry(g, self.var_ws, self.C,
                                   width=self.GROUP_W - 32)  # 全宽适配卡片
        self.entry_ws.place(x=16, y=rh + 4)
        self._row_line(g, rh * 2)
        self._label(g, 16, rh * 2 + 12, "Cookie", color=c["label"])
        self.entry_cookie = AppleEntry(g, self.var_cookie, self.C,
                                       width=self.GROUP_W - 32 - 30, show="*")
        self.entry_cookie.place(x=16, y=rh * 3 + 4)
        self._help_cloud = tk.Label(g, text="ⓘ", font=FONT_SMALL, bg=c["group"],
                                    fg=c["label"], cursor="hand2")
        self._help_cloud.place(x=self.GROUP_W - 16 - 22, y=rh * 3 + 10)
        self._help_cloud.bind("<Button-1>",
                              lambda e: self._show_help(CLOUD_HELP, "官网费用同步"))
        self._row_line(g, rh * 4)
        self.btn_oauth = AppleButton(g, "打开官网", self._oauth_login, self.C,
                                     width=78, height=24, primary=True)
        self.btn_oauth.place(x=16, y=rh * 4 + 10)
        self.btn_cloud_test = AppleButton(g, "测试读取", self._test_cloud, self.C,
                                          width=78, height=24)
        self.btn_cloud_test.place(x=100, y=rh * 4 + 10)
        self._check(g, 190, rh * 4 + 10, "启用官网费用同步", self.var_cloud_on
                    ).place(x=190, y=rh * 4 + 10)
        self.lbl_cloud = tk.Label(g, text="", font=FONT_SMALL, bg=c["group"],
                                  fg=c["status"])
        self.lbl_cloud.place(x=16, y=rh * 5 + 12)
        g.configure(height=rh * 6)
        _round_rect(g, 1, 1, self.GROUP_W - 1, rh * 6 - 1, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        y += rh * 6 + 26

        # ---- 关于 ----
        g = self._group(y, "关于")
        y += 40
        self._label(g, 16, 12, "版本 0.3", color=c["label"])
        self.btn_dir = AppleButton(g, "打开数据目录", self._open_dir, self.C,
                                   width=110, height=24)
        self.btn_dir.place(x=self.GROUP_W - 16 - 110, y=10)
        g.configure(height=rh)
        _round_rect(g, 1, 1, self.GROUP_W - 1, rh - 1, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        y += rh + 26

        # ---- 高级设置（折叠，默认收起） ----
        self._content_base = y          # 高级组标题前的基线高度
        self.adv_card = self._group(y, "")
        self.adv_h = rh * 4 + 6
        self._label(self.adv_card, 16, rh + 8, "opencode.db 路径", color=c["label"])
        self._help_db = tk.Label(self.adv_card, text="ⓘ", font=FONT_SMALL,
                                 bg=c["group"], fg=c["label"], cursor="hand2")
        self._help_db.place(x=150, y=rh + 10)
        self._help_db.bind("<Button-1>",
                           lambda e: self._show_help(HELP_TEXT, "关于 opencode.db"))
        self.entry = AppleEntry(self.adv_card, self.var_path, self.C, width=230)
        self.btn_browse = AppleButton(self.adv_card, "浏览…", self._browse, self.C,
                                      width=56, height=24)
        self.btn_probe = AppleButton(self.adv_card, "探测", self._probe, self.C,
                                     width=56, height=24)
        self.btn_test = AppleButton(self.adv_card, "测试读取", self._test_read, self.C,
                                    width=78, height=24)
        self.lbl_probe = tk.Label(self.adv_card, text="", font=FONT_SMALL,
                                  bg=c["group"], fg=c["status"])
        self._set_adv(False)

        # content 用 place 布局不算入请求尺寸（1x1）→ 显式设置宽度与总高度
        self.content.configure(width=W, height=self._content_base + self.ROW_H + 12)
        self.scroll.configure(scrollregion=(0, 0, W, self._content_base + self.ROW_H + 12))
        self.content.update_idletasks()

    def _set_adv(self, show):
        """高级设置折叠/展开。标题行始终可见，内容展开时才显示。"""
        c = self.C
        self.adv_card.delete("all")
        arrow = "▾" if show else "▸"
        self.adv_card.create_text(16, 22, text=arrow, font=FONT_LABEL,
                                  fill=c["label"], tags="adv_toggle")
        self.adv_card.create_text(30, 22, text="高级设置", font=FONT_SECTION,
                                  fill=c["label"], tags="adv_toggle")
        self.adv_card.tag_bind("adv_toggle", "<Button-1>",
                               lambda e: self._toggle_adv())
        self.adv_card.configure(height=self.adv_h if show else self.ROW_H)
        _round_rect(self.adv_card, 1, 1, self.GROUP_W - 1,
                    self.adv_card.winfo_reqheight() - 1, 10,
                    fill=c["group"], outline=c["group_line"], width=1)
        if show:
            self.entry.place(x=16, y=self.ROW_H + 4)
            self.btn_browse.place(x=250, y=self.ROW_H + 5)
            self.btn_probe.place(x=310, y=self.ROW_H + 5)
            self.btn_test.place(x=16, y=self.ROW_H * 2 + 5)
            self.lbl_probe.place(x=102, y=self.ROW_H * 2 + 9)
        else:
            for wdg in (self.entry, self.btn_browse, self.btn_probe,
                        self.btn_test, self.lbl_probe):
                wdg.place_forget()
        # 内容总高 = 基线 + 高级区实际高度 → 滚动区可到底
        total = self._content_base + (self.adv_h if show else self.ROW_H) + 12
        self.content.configure(height=total)
        self.scroll.configure(scrollregion=(0, 0, W, total))
        self.content.update_idletasks()

    def _toggle_adv(self):
        self._set_adv(not self.var_adv.get())
        self.var_adv.set(not self.var_adv.get())

    # ---------- 滚动 ----------
    def _on_scroll(self, e):
        delta = getattr(e, "delta", 0)
        if delta == 0:  # Button-4/5
            delta = 120 if e.num == 4 else -120
        self.scroll.yview_scroll(-1 if delta > 0 else 1, "units")

    # ---------- 外观/行为 ----------
    def _preview_alpha(self, value):
        try:
            self.master.attributes("-alpha", float(value))
            self.attributes("-alpha", float(value))  # 设置窗同步
            self.lbl_alpha.config(text=f"{int(round(float(value) * 100))}%")
        except (ValueError, tk.TclError):
            pass

    def _apply_theme(self):
        self.C = theme.get_palette(self.var_theme.get())
        for child in self.winfo_children():
            child.destroy()
        self._build_frame()
        self._bind_drag()

    def _step_refresh(self, d):
        opts = [1, 2, 5, 10, 30]
        cur = int(self.var_refresh.get())
        idx = opts.index(cur) if cur in opts else 0
        self.var_refresh.set(opts[(idx + d) % len(opts)])
        self.lbl_refresh.config(text=f"{self.var_refresh.get()} 分钟")

    # ---------- 高级/连接 ----------
    def _browse(self):
        path = filedialog.askopenfilename(
            title="选择 opencode.db",
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")])
        if path:
            self.var_path.set(path)
            self.lbl_probe.config(text="")

    def _probe(self):
        p = config.detect_db(self.var_path.get().strip() or None)
        if p:
            self.var_path.set(str(p))
            self.lbl_probe.config(text="✅ 已找到", fg=self.C["green"])
        else:
            self.lbl_probe.config(text="⚠ 未找到该路径", fg=self.C["orange"])

    def _test_read(self):
        path = self.var_path.get().strip() or None
        p = config.detect_db(path)
        if p is None:
            self.lbl_probe.config(text="⚠ 路径不存在", fg=self.C["orange"])
            return
        try:
            conn = db_reader.open_db(p)
            sessions = db_reader.fetch_sessions(conn)
            conn.close()
            self.lbl_probe.config(text=f"✅ 读取成功：{len(sessions)} 个会话",
                                  fg=self.C["green"])
        except db_reader.DbError as e:
            self.lbl_probe.config(text=f"❌ {e}", fg=self.C["red"])

    # ---------- 帮助弹窗 ----------
    def _show_help(self, text, title):
        top = tk.Toplevel(self)
        top.overrideredirect(True)
        top.configure(bg=KEY)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.95)
        top.attributes("-transparentcolor", KEY)
        hw, hh = 330, 260
        cv = tk.Canvas(top, width=hw, height=hh, bg=KEY, highlightthickness=0, bd=0)
        cv.pack()
        _round_rect(cv, 4, 4, hw - 4, hh - 4, 14, fill=self.C["group"], outline="")
        cv.create_text(18, 22, text=title, font=("Segoe UI", 11, "bold"),
                       fill=self.C["main"], anchor="w")
        tk.Label(top, text=text, font=("Segoe UI", 9), justify="left",
                 fg=self.C["main"], bg=self.C["group"], anchor="nw"
                 ).place(x=18, y=40, width=hw - 36)
        AppleButton(top, "知道了", top.destroy, self.C, width=70, height=26,
                    primary=True).place(x=hw - 18 - 70, y=hh - 36)
        top.update_idletasks()
        x = self.winfo_rootx() + (W - hw) // 2
        y = self.winfo_rooty() + (H - hh) // 2
        top.geometry(f"+{max(4, x)}+{max(4, y)}")

    # ---------- 官网同步 ----------
    def _oauth_login(self):
        """打开官网：用系统默认浏览器（任何电脑/浏览器兼容），复制 Cookie 后自动识别。"""
        import webbrowser
        webbrowser.open("https://opencode.ai/workspace")
        self.lbl_cloud.config(
            text="已用默认浏览器打开官网，F12 → Network 复制 Cookie 后自动识别",
            fg=self.C["status"])
        self.after(800, self._check_clipboard)

    def _check_clipboard(self):
        """剪贴板自动识别官网 cookie（auth=Fe26.2*... 格式），复制即填。"""
        import re as _re
        try:
            text = self.clipboard_get()
        except Exception:
            self.after(1000, self._check_clipboard)
            return
        m = _re.search(r"auth=Fe26\.2\*[A-Za-z0-9*._-]{50,}", text)
        if m and m.group(0) != self.var_cookie.get():
            self.var_cookie.set(m.group(0))
            self.lbl_cloud.config(text="✅ 已自动识别官网 Cookie！点测试读取验证", fg=self.C["green"])
            # 尝试自动填 workspace（用 cookie 查）
            def work():
                try:
                    ws = fetch_workspace_id(m.group(0))
                    if ws:
                        self.after(0, lambda: self.var_ws.set(ws))
                except Exception:
                    pass
            threading.Thread(target=work, daemon=True).start()
            return
        self.after(1000, self._check_clipboard)

    def _oauth_done(self, cookie, ws):
        self.var_cookie.set("auth=" + cookie)
        if ws:
            self.var_ws.set(ws)
        self.lbl_cloud.config(text="✅ 已获取，点测试读取验证", fg=self.C["green"])

    def _oauth_fail(self, err):
        self.lbl_cloud.config(text=f"❌ {err}", fg=self.C["red"])

    def _test_cloud(self):
        ws = self.var_ws.get().strip()
        cookie = self.var_cookie.get().strip()
        if not ws or not cookie:
            self.lbl_cloud.config(text="⚠ 请先填写 Workspace ID 和 Cookie",
                                  fg=self.C["orange"])
            return
        try:
            import datetime
            by_day = month_costs(ws, cookie, months=1)
            days = sorted(by_day.keys())[-3:]
            total = sum(by_day[d]["total"] for d in days)
            if not days:
                self.lbl_cloud.config(text="✅ 连接成功（本月暂无费用记录）",
                                      fg=self.C["green"])
            else:
                self.lbl_cloud.config(
                    text=f"✅ 最近 {len(days)} 天合计 ${total:.2f}",
                    fg=self.C["green"])
        except CloudError as e:
            self.lbl_cloud.config(text=f"❌ {e}", fg=self.C["red"])
        except Exception as e:
            self.lbl_cloud.config(text=f"❌ 同步失败：{e}", fg=self.C["red"])

    def _open_dir(self):
        try:
            os.startfile(str(config.get_data_dir()))
        except OSError:
            pass

    # ---------- 保存 ----------
    def _save(self):
        cfg = config.load_config()
        cfg["db_path"] = self.var_path.get().strip() or None
        cfg["autostart"] = bool(self.var_auto.get())
        cfg["theme"] = self.var_theme.get()
        cfg["window_alpha"] = round(float(self.var_alpha.get()), 2)
        cfg["refresh_interval"] = int(self.var_refresh.get())
        cfg["number_format"] = self.var_format.get()
        cfg["topmost_on_start"] = bool(self.var_topmost.get())
        cfg["lock_position"] = bool(self.var_lock.get())
        cfg["click_through"] = bool(self.var_click.get())
        cfg["display_fields"] = [f for f, v in self.var_fields.items() if v.get()]
        cfg["cloud_workspace_id"] = self.var_ws.get().strip()
        cfg["cloud_cookie"] = self.var_cookie.get().strip()
        cfg["cloud_enabled"] = bool(self.var_cloud_on.get())
        config.save_config(cfg)
        m = self.master
        if hasattr(m, "set_appearance"):
            m.set_appearance(theme_cfg=cfg["theme"], alpha=cfg["window_alpha"])
        for name, arg in (("set_refresh_interval", cfg["refresh_interval"]),
                          ("set_number_format", cfg["number_format"]),
                          ("set_lock_position", cfg["lock_position"]),
                          ("set_display_fields", cfg["display_fields"]),
                          ("set_click_through", cfg["click_through"]),
                          ("set_cloud", (cfg["cloud_workspace_id"], cfg["cloud_cookie"],
                                         cfg["cloud_enabled"]))):
            if hasattr(m, name):
                getattr(m, name)(arg)
        if not config.set_autostart(cfg["autostart"]):
            self.lbl_probe.config(text="⚠ 开机自启设置失败", fg=self.C["orange"])
            return
        if self._on_saved:
            self._on_saved()
        self.destroy()

    # ---------- 拖动/定位 ----------
    def _bind_drag(self):
        self._dx = self._dy = 0

        def on_press(e):
            self._dx, self._dy = e.x, e.y

        def on_drag(e):
            self.geometry(f"+{self.winfo_x() + e.x - self._dx}"
                          f"+{self.winfo_y() + e.y - self._dy}")

        self.canvas.bind("<ButtonPress-1>", on_press)
        self.canvas.bind("<B1-Motion>", on_drag)

    def _place(self):
        self.update_idletasks()
        x = self.master.winfo_rootx() + (self.master.winfo_width() - W) // 2
        y = self.master.winfo_rooty() + (self.master.winfo_height() - H) // 2
        x = max(4, min(x, self.winfo_screenwidth() - W))
        y = max(4, min(y, self.winfo_screenheight() - H))
        self.geometry(f"+{x}+{y}")
        self.lift()
        self.after(300, self._force_front)  # 防被其他置顶窗口盖住

    def _force_front(self) -> None:
        """Win32 层强制 z-order 最前（64 位安全：显式声明 HWND 类型防句柄截断）。"""
        import ctypes
        from ctypes import wintypes
        try:
            u = ctypes.windll.user32
            u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                       ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            hwnd = self.winfo_id()
            parent = u.GetParent(hwnd)
            if parent:
                hwnd = parent
            u.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(-1), 0, 0, 0, 0,
                           0x0001 | 0x0002 | 0x0010)
            u.BringWindowToTop(wintypes.HWND(hwnd))
        except Exception:
            pass

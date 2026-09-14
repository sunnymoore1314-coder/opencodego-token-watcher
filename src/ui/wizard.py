"""首启向导：Apple 风格（与主窗/设置窗同一视觉语言）。

自动探测 opencode.db → 成功：今日用量预览 → 开始使用；
失败：三分状态提示（未安装/无数据/读失败）+ 文档入口 + 跳过。
独立 Tk 根窗口（避免同进程多 Tk 实例），运行完毕后 destroy。
"""
from __future__ import annotations

import os
from pathlib import Path

import tkinter as tk
from tkinter import filedialog

from src import config, pipeline, theme
from src.aggregator import format_tokens

W, H = 420, 330
KEY = theme.KEY
DOC_URL = "https://opencode.ai/docs/"
TROUBLE_URL = "https://opencode.ai/docs/troubleshooting/"
DEFAULT_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw) -> int:
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return cv.create_polygon(pts, smooth=True, **kw)


class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("OpenCode 用量监测 · 首次使用")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.theme_cfg = config.load_config().get("theme", "system")
        self.C = theme.get_palette(self.theme_cfg)
        self.configure(bg=KEY)
        self.attributes("-alpha", 0.92)
        self.attributes("-transparentcolor", KEY)
        self.overrideredirect(True)
        self._cfg = config.load_config()
        self._found: str | None = None
        self.canvas = tk.Canvas(self, width=W, height=H, bg=KEY,
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self._build()
        self._bind_drag()
        self._probe()
        self._center()

    def _center(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth() - W) // 2
        y = (self.winfo_screenheight() - H) // 2
        self.geometry(f"{W}x{H}+{x}+{y}")

    def _build(self):
        C = self.C
        cv = self.canvas
        _round_rect(cv, 4, 4, W - 4, H - 4, 16, fill=C["card"], outline="")
        # 用 tk.Label 渲染混合串（create_text 对"字母+中文"在 exe 下会字体 fallback 乱码）
        cv.create_text(18, 24, text="欢迎使用 OpenCode 用量监测",
                       font=("Segoe UI", 13, "bold"), fill=C["main"], anchor="w")
        cv.create_text(W - 18, 24, text="✕", font=("Segoe UI", 9), fill=C["label"],
                       anchor="e", tags="close")
        cv.create_line(18, 40, W - 18, 40, fill=C["line"], width=1)
        tk.Label(self, text="自动检测本机的 opencode.db（OpenChamber / opencode 共用）\n"
                            "找到即可直接使用，无需其他配置。",
                 font=("Segoe UI", 9), fg=C["label"], bg=C["card"], justify="left",
                 wraplength=W - 36
                 ).place(x=18, y=52)
        self.lbl_path = tk.Label(self, text="检测中…", font=("Consolas", 10),
                                 fg=C["main"], bg=C["card"], wraplength=W - 36,
                                 justify="left", anchor="w")
        self.lbl_path.place(x=18, y=100)
        # 文档链接（失败时显示）
        self.lbl_doc = tk.Label(self, text="如何找到 opencode.db？", font=("Segoe UI", 8),
                                fg=C["today"], bg=C["card"], cursor="hand2")
        self.lbl_doc.place(x=18, y=124)
        self.lbl_doc.bind("<Button-1>", lambda e: os.startfile(DOC_URL))
        self.lbl_doc.place_forget()
        # 按钮行
        self.btn_probe = self._btn("重新探测", 18, 156, self._probe)
        self.btn_browse = self._btn("手动选择…", 116, 156, self._browse)
        self.btn_skip = self._btn("跳过（稍后设置）", 18, 292, self._skip)
        self.btn_skip.place_configure(width=148, height=26)
        self.btn_start = tk.Button(self, text="开始使用", command=self._finish,
                                   font=("Segoe UI", 9, "bold"), bg=C["today"],
                                   fg="#FFFFFF", activebackground=C["btn_hover"],
                                   activeforeground="#FFFFFF", relief="flat",
                                   bd=0, padx=18, pady=5, cursor="hand2")
        self.btn_start.place(x=W - 18 - 96, y=156, width=96, height=30)
        # 今日用量预览区（探测成功时显示）
        cv.create_line(18, 204, W - 18, 204, fill=C["line"], width=1)
        cv.create_text(18, 222, text="今日用量预览", font=("Segoe UI", 9),
                       fill=C["main"], anchor="w")
        self.lbl_preview = tk.Label(self, text="", font=("Segoe UI", 9),
                                    fg=C["main"], bg=C["card"], justify="left",
                                    anchor="w")
        self.lbl_preview.place(x=18, y=244)
        self.pv_canvas = tk.Canvas(self, width=W - 36, height=6, bg=C["card"],
                                   highlightthickness=0, bd=0)
        self.pv_canvas.place(x=18, y=272)
        cv.tag_bind("close", "<Button-1>", lambda e: self._skip())

    def _btn(self, text, x, y, cmd):
        C = self.C
        b = tk.Button(self, text=text, command=cmd, font=("Segoe UI", 9),
                      bg=C["btn"], fg=C["main"], activebackground=C["btn_hover"],
                      relief="flat", bd=0, padx=12, pady=5, cursor="hand2")
        b.place(x=x, y=y, width=86, height=30)
        return b

    def _bind_drag(self):
        self._dx = self._dy = 0

        def on_press(e):
            self._dx, self._dy = e.x, e.y

        def on_drag(e):
            x = self.winfo_x() + e.x - self._dx
            y = self.winfo_y() + e.y - self._dy
            self.geometry(f"+{x}+{y}")

        self.canvas.bind("<ButtonPress-1>", on_press)
        self.canvas.bind("<B1-Motion>", on_drag)

    # ---------- 逻辑 ----------
    def _probe(self):
        """探测 db 并分状态显示（成功：预览今日用量；失败：三分提示）。"""
        C = self.C
        p = config.detect_db(self._cfg.get("db_path"))
        self._found = str(p) if p else None
        self.lbl_doc.place_forget()
        if p:
            self.lbl_path.config(text=f"✅ 已找到：{p}", fg=C["green"])
            self.btn_start.config(text="开始使用", command=self._finish)
            self._show_preview(p)
            return
        # 失败三分
        data_dir = Path.home() / ".local" / "share" / "opencode"
        if not data_dir.exists():
            msg = "未检测到 opencode 数据目录。\n请先安装并运行 opencode 产生数据。"
            self.btn_start.config(text="打开官方文档",
                                  command=lambda: os.startfile(DOC_URL))
        elif not DEFAULT_DB.exists():
            msg = "已安装但还没有数据。运行一次 opencode 会自动生成。\n"
            msg += f"默认路径：{DEFAULT_DB}"
            self.btn_start.config(text="手动选择…", command=self._browse)
        else:
            # 路径存在但读失败（探测用的是显式路径时）
            msg = "数据库无法读取（可能被占用或损坏）。"
            self.btn_start.config(text="手动选择…", command=self._browse)
            self.lbl_doc.config(text="疑难排查 →", fg=C["today"])
            self.lbl_doc.bind("<Button-1>", lambda e: os.startfile(TROUBLE_URL))
            self.lbl_doc.place(x=18, y=124)
        self.lbl_path.config(text=f"⚠ {msg}", fg=C["orange"])
        self.lbl_preview.config(text="")
        self.pv_canvas.delete("all")

    def _show_preview(self, db_path):
        """探测成功：显示今日用量预览（同时预热缓存）。"""
        C = self.C
        try:
            by_day, _err = pipeline.refresh(db_path)
        except Exception:
            by_day = None
        import datetime
        today = datetime.date.today().isoformat()
        s = by_day.get(today) if by_day else None
        if s is None:
            self.lbl_preview.config(
                text="数据库里还没有会话数据，运行一次 opencode 后会自动更新")
            self.pv_canvas.delete("all")
            return
        text = (f"输入 {format_tokens(s.input)}    输出 {format_tokens(s.output)}"
                f"    命中率 {s.hit_rate:.1f}%" if s.hit_rate is not None
                else f"输入 {format_tokens(s.input)}    输出 {format_tokens(s.output)}")
        self.lbl_preview.config(text=text, fg=C["main"])
        self.pv_canvas.delete("all")
        if s.hit_rate is not None:
            color = C["green"] if s.hit_rate >= 70 else (C["orange"] if s.hit_rate >= 30 else C["red"])
            w = int((W - 36) * s.hit_rate / 100)
            _round_rect(self.pv_canvas, 0, 0, w, 6, 3, fill=color, outline="")

    def _browse(self):
        path = filedialog.askopenfilename(
            title="选择 opencode.db",
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")])
        if path:
            self._cfg["db_path"] = path
            self._probe()

    def _finish(self):
        config.save_config(self._cfg)
        self.destroy()

    def _skip(self):
        """跳过：写 config（保持 db_path），向导不再重复弹。"""
        config.save_config(self._cfg)
        self.destroy()

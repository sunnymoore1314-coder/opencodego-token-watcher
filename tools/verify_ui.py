"""UI 验证：Canvas 渲染 + 交互状态（导航/粒度切换）断言。

用法: python tools/verify_ui.py
"""
import datetime
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.aggregator import DayStats
from src.ui.window import UsageWindow
from src.ui.wizard import Wizard

TODAY = datetime.date.today()
YESTERDAY = TODAY - datetime.timedelta(days=1)

# 假数据：今天实际输入 17.7M（命中 98.2% 绿），昨天低命中（与 pipeline 类型一致：DayStats）
FAKE_BY_DAY = {
    TODAY.isoformat(): DayStats(input=17_737_212, output=2_150_663,
                                cache_read=995_650_560, cache_write=0),
    YESTERDAY.isoformat(): DayStats(input=900, output=100,
                                    cache_read=100, cache_write=0),  # 命中 10%
}


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'✅' if cond else '❌'} {name} {detail}")
    if not cond:
        raise SystemExit(1)


win = UsageWindow()
win.set_data(FAKE_BY_DAY, None)
win.update_idletasks()
cv = win.canvas


def item_text(tag):
    ids = cv.find_withtag(tag)
    return cv.itemcget(ids[0], "text") if ids else None


def bar_fill():
    ids = cv.find_withtag("bar")
    return cv.itemcget(ids[0], "fill") if ids else None


print("--- 布局/窗口 ---")
check("窗口尺寸", win.winfo_width() == 250 and win.winfo_height() == 182,
      f"(实际 {win.winfo_width()}x{win.winfo_height()})")
check("置顶", win.attributes("-topmost") == 1)
check("半透明", 0 < win.attributes("-alpha") < 1)

print("--- 今日渲染（day 粒度，默认）---")
check("范围文本", item_text("range") ==
      f"{TODAY.month}月{TODAY.day}日(周{'一二三四五六日'[TODAY.weekday()]})",
      f"(实际 {item_text('range')})")
check("输入缩写", item_text("val_输入") == "17.7M", f"(实际 {item_text('val_输入')})")
check("输出缩写", item_text("val_输出") == "2.2M", f"(实际 {item_text('val_输出')})")
check("命中率文本", item_text("val_命中率") == "98.2%")
check("进度条绿色(≥70)", bar_fill() == win.C["green"], f"(实际 {bar_fill()})")
check("状态栏", item_text("status") == f"⟳ 已同步 {win._sync_time} · 1分钟自动")

print("--- 交互：◀ 翻到昨天 ---")
win._nav(-1)
check("范围=昨天", item_text("range") ==
      f"{YESTERDAY.month}月{YESTERDAY.day}日(周{'一二三四五六日'[YESTERDAY.weekday()]})",
      f"(实际 {item_text('range')})")
check("命中率 10%（<30 → 红）", item_text("val_命中率") == "10.0%")
check("进度条红色(<30)", bar_fill() == win.C["red"], f"(实际 {bar_fill()})")

print("--- 交互：切换粒度 ---")
win._set_gran("week")
start = TODAY - datetime.timedelta(days=TODAY.weekday())
end = start + datetime.timedelta(days=6)
check("周范围", item_text("range") == f"{start.month}月{start.day}日~{end.month}月{end.day}日",
      f"(实际 {item_text('range')})")
win._set_gran("month")
check("月范围", item_text("range") == f"{TODAY.year}年{TODAY.month}月",
      f"(实际 {item_text('range')})")
win._set_gran("day")

print("--- 日历弹窗（Apple 风格 + toggle）---")
win._open_calendar()
check("日历已创建", win._cal.winfo_exists())
cal = win._cal
check("日历半透明", 0 < cal.attributes("-alpha") < 1)
check("日历抠角", "#010203" in str(cal.attributes("-transparentcolor")))
check("42 个日期格", len([t for t in cal.canvas.find_all() if "cal_day_" in str(cal.canvas.gettags(t))]) == 42)
title_ids = cal.canvas.find_withtag("cal_title")
check("标题正确", cal.canvas.itemcget(title_ids[0], "text") == f"{TODAY.year}年{TODAY.month}月")
cal._pick(YESTERDAY)  # 模拟点选昨天（真实路径：回调 + 关闭）
check("日历选择→day 粒度+游标", win.gran == "day" and win.cursor == YESTERDAY)
check("日历已关闭", not win._cal.winfo_exists())
win._open_calendar()  # 再打开
check("再打开成功", win._cal.winfo_exists())
win._open_calendar()  # toggle 关闭
check("toggle 关闭日历", win._cal is None)

print("--- 右键菜单 ---")
check("菜单 7 项", win._menu.index("end") + 1 == 7, f"(实际 {win._menu.index('end') + 1})")
check("穿透菜单项", "鼠标穿透" in win._menu.entrycget(2, "label"))

print("--- 设置窗（Apple 风格）---")
win._open_settings()
settings_wins = [c for c in win.winfo_children() if c.winfo_class() == "Toplevel"]
check("设置窗已创建", len(settings_wins) == 1)
if settings_wins:
    s = settings_wins[0]
    check("设置窗抠角", "#010203" in str(s.attributes("-transparentcolor")))
    check("设置窗半透明", 0 < s.attributes("-alpha") < 1)
    check("设置窗含保存按钮", hasattr(s, "btn_save"))
    s.destroy()

print("--- 无数据状态 ---")
win.set_data(None, "未找到数据源，请在设置中指定 opencode.db 路径")
check("错误状态栏", item_text("status") ==
      "未找到数据源，请在设置中指定 opencode.db 路径（右键 → 设置 可指定路径）",
      f"(实际 {item_text('status')})")
check("无数据时命中率=—", item_text("val_命中率") == "—")
check("无数据时无进度条", len(cv.find_withtag("bar")) == 0)

check("颜色常量互异", len({win.C["green"], win.C["orange"], win.C["red"]}) == 3)
win.destroy()

# ============ 新增功能断言（四角缩放 / AlphaSlider / 首启向导 / 测试读取） ============

print("--- 四角缩放（360x260 → 恢复 250x182）---")
win2 = UsageWindow()
win2.set_data(FAKE_BY_DAY, None)
win2._sw, win2._sh = 360, 260
win2.geometry("360x260")  # 窗口 geometry 同步（canvas 尺寸受窗口限制）
win2.canvas.config(width=360, height=260)  # 与手势 on_drag 一致：先改 canvas 尺寸再 render
win2.render()
win2.update()  # 完整 pump 使 geometry 生效
cv2 = win2.canvas


def font_size_of(cv, tag: str) -> int:
    """取 canvas 上 tag 的字体字号（itemcget font → 数字 token）。"""
    ids = cv.find_withtag(tag)
    if not ids:
        return -1
    for tok in cv.itemcget(ids[0], "font").split():
        if tok.isdigit():
            return int(tok)
    return -1


check("缩放后 canvas 360x260",
      cv2.winfo_width() == 360 and cv2.winfo_height() == 260,
      f"(实际 {cv2.winfo_width()}x{cv2.winfo_height()})")
check("缩放后字号放大(≥14)", font_size_of(cv2, "val_输入") >= 14,
      f"(实际 {font_size_of(cv2, 'val_输入')})")
check("缩放后 grip 存在(2 个)", len(cv2.find_withtag("grip")) == 2,
      f"(实际 {len(cv2.find_withtag('grip'))})")
win2._sw, win2._sh = 250, 182
win2.canvas.config(width=250, height=182)
win2.render()
win2.update_idletasks()
check("恢复 canvas 250x182",
      cv2.winfo_width() == 250 and cv2.winfo_height() == 182,
      f"(实际 {cv2.winfo_width()}x{cv2.winfo_height()})")
check("恢复后字号回 10", font_size_of(cv2, "val_输入") == 10,
      f"(实际 {font_size_of(cv2, 'val_输入')})")
win2.destroy()

print("--- AlphaSlider（透明度 0.5 → 0.72）---")
win3 = UsageWindow()
win3._open_settings()
st_wins = [c for c in win3.winfo_children() if c.winfo_class() == "Toplevel"]
st = st_wins[0]
check("设置窗含 AlphaSlider", hasattr(st, "scale") and hasattr(st, "var_alpha"))
st.scale._set_frac(0.5)
alpha_val = float(st.var_alpha.get())
check("var_alpha ≈ 0.72", abs(alpha_val - 0.72) <= 0.01, f"(实际 {alpha_val})")
win_alpha = float(win3.attributes("-alpha"))
check("主窗 alpha 同步 ≈ 0.72", abs(win_alpha - 0.72) <= 0.01, f"(实际 {win_alpha})")

print("--- 测试读取 ---")
st.var_path.set("C:/definitely/not/exist/opencode.db")
st._test_read()
probe_text = st.lbl_probe.cget("text")
check("不存在路径→提示不存在", "不存在" in probe_text, f"(实际 {probe_text!r})")
st.var_path.set("")
st._test_read()
probe_text = st.lbl_probe.cget("text")
check("空路径→读取成功", "读取成功" in probe_text, f"(实际 {probe_text!r})")
st.destroy()
win3.destroy()

print("--- 首启向导（临时 APPDATA，真实 db 探测成功态）---")
old_appdata = os.environ.get("APPDATA")
tmp_appdata = tempfile.mkdtemp(prefix="verify_ui_appdata_")
os.environ["APPDATA"] = tmp_appdata
try:
    wz = Wizard()
    path_text = wz.lbl_path.cget("text")
    check("成功态:已找到 db", "已找到" in path_text, f"(实际 {path_text!r})")
    check("成功态:按钮=开始使用", wz.btn_start.cget("text") == "开始使用",
          f"(实际 {wz.btn_start.cget('text')!r})")
    preview_text = wz.lbl_preview.cget("text")
    check("成功态:预览区非空", bool(preview_text.strip()), f"(实际 {preview_text!r})")
    wz._skip()
    wz_cfg = Path(tmp_appdata) / "opencodego-token-watcher" / "config.json"
    check("跳过已写 config", wz_cfg.exists(), f"(实际 {wz_cfg})")
finally:
    if old_appdata is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = old_appdata
    shutil.rmtree(tmp_appdata, ignore_errors=True)

print("UI VERIFY: PASS")

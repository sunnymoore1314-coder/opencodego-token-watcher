"""直接抓取主窗口或设置窗口像素，供 UI 视觉验收。

用法：
  python tools/print_window.py main.bmp
  python tools/print_window.py main.bmp --settings settings.bmp
"""
from __future__ import annotations

import argparse
import ctypes
import os
import struct
import sys
import tempfile
from ctypes import wintypes as wt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.aggregator import DayStats
from src.ui.window import FIELD_LABELS, UsageWindow

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 2


def save_bitmap(widget, path: Path) -> None:
    """用 PrintWindow 将一个 Tk 顶层窗口保存为 32bpp BMP。"""
    widget.update_idletasks()
    hwnd = user32.GetParent(widget.winfo_id()) or widget.winfo_id()
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    bitmap = gdi32.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi32.SelectObject(memory_dc, bitmap)
    ok = user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT)
    gdi32.SelectObject(memory_dc, old)
    bmi = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    pixels = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, bmi, 0)
    data = pixels.raw
    header = b"BM" + struct.pack("<IHHI", 54 + len(data), 0, 0, 54) + bmi
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + data)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(memory_dc)
    user32.ReleaseDC(None, screen_dc)
    print(f"PrintWindow={ok} {width}x{height} -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("main_output", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--all-fields", action="store_true")
    args = parser.parse_args()
    old_appdata = os.environ.get("APPDATA")
    try:
        with tempfile.TemporaryDirectory(prefix="opencode-ui-capture-") as tmp:
            os.environ["APPDATA"] = tmp
            win = UsageWindow()
            win.geometry("+20+20")
            win.set_data({win.cursor.isoformat(): DayStats(
                input=1_020_000, output=24_000, cache_read=8_200_000)}, None)
            if args.all_fields:
                win.set_display_fields(list(FIELD_LABELS))
            settings = None
            if args.settings:
                win._open_settings()
                settings = next(child for child in win.winfo_children()
                                if child.winfo_class() == "Toplevel")

            def capture():
                save_bitmap(win, args.main_output.resolve())
                if settings is not None:
                    save_bitmap(settings, args.settings.resolve())
                win._exit()

            win.after(800, capture)
            win.mainloop()
    finally:
        if old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old_appdata


if __name__ == "__main__":
    main()

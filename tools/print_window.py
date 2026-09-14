"""窗口内容自抓取诊断：PrintWindow 直接抓窗口像素存 BMP，确认渲染内容。

用法: python tools/print_window.py <输出.bmp>
"""
import ctypes
import struct
import sys
from ctypes import wintypes as wt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ui.window import UsageWindow

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
PW_RENDERFULLCONTENT = 2

if "--no-topmost" in sys.argv:
    import src.ui.window as W2
    _orig_init = W2.UsageWindow.__init__

    def patched_init(self):
        _orig_init(self)
        self.attributes("-topmost", False)

    W2.UsageWindow.__init__ = patched_init


def save_bitmap(hdc, hbmp, w, h, path):
    """把兼容位图按 32bpp 写成 BMP 文件。"""
    bmi = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(hdc, hbmp, 0, h, buf, bmi, 0)
    # BMP header
    row = w * 4
    data = buf.raw
    file_size = 54 + len(data)
    header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54) + bmi + data
    Path(path).write_bytes(header)


win = UsageWindow()
win.geometry("+20+20")
win.render({"input": 1140390, "output": 2596817, "hit_rate": 98.2},
           range_text="8月12日(周二)", status="已同步 15:30")


def capture():
    """mainloop 稳定运行后再抓取窗口内容。"""
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    print(f"窗口 rect: {w}x{h} at ({rect.left},{rect.top})")

    hdc = user32.GetDC(None)
    memdc = gdi32.CreateCompatibleDC(hdc)
    hbmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(memdc, hbmp)
    ok = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)
    gdi32.SelectObject(memdc, old)

    out = next((a for a in sys.argv[1:] if not a.startswith("--")),
               r"C:\Users\14681\AppData\Local\Temp\win_dump.bmp")
    save_bitmap(memdc, hbmp, w, h, out)
    print(f"PrintWindow={ok} 已保存: {out}")
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(None, hdc)
    win.destroy()


win.after(1500, capture)
win.mainloop()

"""系统托盘图标（零依赖：ctypes + Shell_NotifyIconW）。

- message-only 窗口接收托盘回调（WM_APP+1，lParam 区分右键/双击/左键）
- 后台线程 GetMessage 循环，事件通过回调切回 Tk 主线程
- 图标从 .ico 文件加载（打包后走 sys._MEIPASS）
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import threading
from pathlib import Path

WM_TRAY = 0x8000                      # WM_APP
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x0205, 0x0203
LR_LOADFROMFILE = 0x0010
IMAGE_ICON = 1


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.c_uint),
        ("uFlags", ctypes.c_uint),
        ("uCallbackMessage", ctypes.c_uint),
        ("hIcon", ctypes.wintypes.HANDLE),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_uint),
        ("dwStateMask", ctypes.c_uint),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeoutOrVersion", ctypes.c_uint),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_uint),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.wintypes.HANDLE),
    ]


def _resource_path(name: str) -> Path:
    """打包后从 _MEIPASS 读取资源，开发期取项目根。"""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent)
    return Path(base) / name


def _load_icon(icon_path: Path):
    user32 = ctypes.windll.user32
    user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.LoadImageW.restype = ctypes.c_void_p
    return user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)


class TrayIcon:
    """托盘图标。回调：on_menu(事件) 右键弹菜单；on_show() 左键双击显示窗口。"""

    def __init__(self, hwnd, tooltip: str = "OpenCodeGO Token Watcher",
                 icon_name: str = "assets/app.ico"):
        self._hwnd = hwnd
        self._uID = 1
        self._tooltip = tooltip
        self._icon = _load_icon(_resource_path(icon_name))
        self._thread = None
        self._stop = False
        self.on_menu = None
        self.on_show = None
        self._msg_hwnd = self._create_msg_window()
        self._add()

    # ---------- 消息窗口 ----------
    def _create_msg_window(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                          ctypes.c_void_p, ctypes.c_void_p]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
        user32.CreateWindowExW.restype = ctypes.c_void_p
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_void_p, ctypes.c_void_p)
        hinst = kernel32.GetModuleHandleW(None)

        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY:
                if lparam == WM_RBUTTONUP and self.on_menu:
                    self.on_menu()
                elif lparam == WM_LBUTTONDBLCLK and self.on_show:
                    self.on_show()
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc = wnd_proc  # 保持引用防 GC

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", ctypes.c_uint),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
            ]

        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(wnd_proc, ctypes.c_void_p).value
        wc.hInstance = hinst
        wc.lpszClassName = "OpenCodeGOTrayMsgWindow"
        user32.RegisterClassW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(
            0, wc.lpszClassName, None, 0, 0, 0, 0, 0,
            ctypes.wintypes.HWND(-3),  # HWND_MESSAGE：message-only 窗口
            None, hinst, None)
        return hwnd

    def _add(self):
        nid = _NotifyIconData()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._msg_hwnd
        nid.uID = self._uID
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon
        nid.szTip = self._tooltip
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._nid = nid
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        """阻塞式消息循环（message-only 窗口的消息）。"""
        user32 = ctypes.windll.user32
        msg = ctypes.wintypes.MSG()
        while not self._stop:
            ret = user32.GetMessageW(ctypes.byref(msg), self._msg_hwnd, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    # ---------- 生命周期 ----------
    def destroy(self):
        self._stop = True
        try:
            ctypes.windll.shell32.Shell_NotifyIconW(
                NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass
        try:
            ctypes.windll.user32.PostMessageW(self._msg_hwnd, 0x0012, 0, 0)  # WM_QUIT
        except Exception:
            pass

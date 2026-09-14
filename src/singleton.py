"""单实例互斥（Windows CreateMutexW；其他平台直接放行）。

- 互斥体按名字互斥（固定字符串），与 exe 文件名/路径无关，打包后依然生效
- 句柄存活到进程退出（进程退出时系统自动释放）；正常退出路径可显式 release()
"""
from __future__ import annotations

import sys

MUTEX_NAME = "opencodego-token-watcher-singleton-mutex"
ERROR_ALREADY_EXISTS = 183

_handle = None  # 持有互斥体句柄直到进程退出，防止被回收


def acquire(mutex_name: str = MUTEX_NAME) -> bool:
    """占用单实例互斥体。True=当前进程是唯一实例；False=已有实例在运行。"""
    global _handle
    if sys.platform != "win32":
        return True  # 非 Windows 无单实例限制
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = kernel32.CreateMutexW(None, False, mutex_name)
    if not handle:
        return True  # 创建失败（极端情况）→ 放行，不阻断启动
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)  # 已有实例：释放本次句柄并返回失败
        return False
    _handle = handle
    return True


def release() -> None:
    """释放互斥体句柄（正常退出路径调用；进程退出时也会自动释放）。"""
    global _handle
    if _handle is not None:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(_handle)
        _handle = None


def notify_already_running() -> None:
    """提示已有实例在运行（原生弹窗，不依赖 Tk）。"""
    import ctypes
    # MB_ICONINFORMATION(0x40) | MB_TOPMOST(0x40000)：本程序置顶运行，提示框也要置顶
    ctypes.windll.user32.MessageBoxW(
        None, "程序已在运行", "OpenCodeGO Token Watcher", 0x40 | 0x40000)

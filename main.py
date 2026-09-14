"""入口：启动用量监测小窗。

用法:
  python main.py                正常启动（首次运行先弹首启向导）
  python main.py --auto-close 3 启动 3 秒后自动关闭（自动化截图验证用）
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from src import config, singleton
from src.ui.window import UsageWindow


def _resource_path(name: str) -> str:
    """资源路径：PyInstaller frozen 时取 sys._MEIPASS，否则取项目根相对路径。"""
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return str(Path(base) / name)


def enable_dpi_awareness() -> None:
    """DPI 感知，防字体模糊（ui-spec 要求；本机 2560x1600 @150%）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        pass


def main() -> None:
    enable_dpi_awareness()
    # 单实例限制：验证模式（--auto-close，自动化截图/并发）跳过检查
    if "--auto-close" not in sys.argv:
        if not singleton.acquire():
            print("已在运行", file=sys.stderr)
            singleton.notify_already_running()
            sys.exit(1)
    if not config.get_config_path().exists():
        from src.ui.wizard import Wizard
        wizard = Wizard()
        if "--auto-close" in sys.argv:
            wizard.after(1000, wizard._skip)  # 验证首启也能进入主窗，不等待手动操作
        wizard.mainloop()  # 首启向导，结束后已保存配置
    win = UsageWindow()  # 启动后自动刷新（窗口内部 after 200ms）
    try:
        win.iconbitmap(_resource_path("assets/app.ico"))  # 窗口/任务栏图标
    except Exception:
        pass  # 图标缺失时不阻塞启动
    if "--auto-close" in sys.argv:
        n = int(sys.argv[sys.argv.index("--auto-close") + 1])
        win.geometry("+20+20")  # 固定位置，便于自动化截图
        win.after(n * 1000, win._exit)
    win.mainloop()
    singleton.release()  # 正常退出路径释放互斥体句柄


if __name__ == "__main__":
    main()

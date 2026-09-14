r"""主题模块：深浅色两套配色（Apple 风格），默认跟随 Windows 系统主题。

系统主题检测：HKCU\...\Themes\Personalize\AppsUseLightTheme（0=深色，1=浅色）
config.json 的 theme 字段：system（默认）/ light / dark
"""
from __future__ import annotations

import sys

# ---- 浅色（macOS 浅色面板）----
LIGHT = {
    "card": "#FFFFFF",        # 卡片底
    "shadow": "#E5E7EB",      # 卡片阴影
    "main": "#1D1D1F",        # 主文字（苹果近黑）
    "label": "#86868B",       # 标签（苹果灰）
    "line": "#F0F0F2",        # 分隔线
    "track": "#E5E5E8",       # 进度条轨道/滑轨（浅色下更明显）
    "status": "#6B7280",      # 状态栏文字
    "muted": "#D1D5DB",       # 弱化文字（日历其他月）
    "today": "#0071E3",       # 苹果蓝（今天高亮/主按钮）
    "btn": "#F2F2F4",         # 次按钮底
    "btn_hover": "#E5E5E8",   # 次按钮悬停
    "green": "#22C55E", "orange": "#F59E0B", "red": "#EF4444",
    # 设置窗（macOS System Settings 风）
    "win_bg": "#F2F2F5",      # 设置窗窗口底（浅灰）
    "group": "#FFFFFF",       # 分组卡片底
    "group_line": "#E5E5EA",  # 组内行分割线
    "entry_bg": "#FFFFFF",    # 输入框底
    "entry_border": "#D0D0D5",# 输入框边框
    "combo_bg": "#FFFFFF",    # 下拉底
}
# ---- 深色（macOS 深色面板）----
DARK = {
    "card": "#2A2A2E",        # 深灰卡片
    "shadow": "#000000",      # 黑色阴影
    "main": "#F5F5F7",        # 主文字（苹果浅色）
    "label": "#A1A1A6",       # 标签（苹果深色灰）
    "line": "#3A3A3C",        # 分隔线
    "track": "#3A3A3C",       # 进度条轨道
    "status": "#98989D",      # 状态栏文字
    "muted": "#48484A",       # 弱化文字
    "today": "#0A84FF",       # 苹果深色蓝
    "btn": "#3A3A3C",         # 次按钮底
    "btn_hover": "#48484A",   # 次按钮悬停
    "green": "#30D158", "orange": "#FF9F0A", "red": "#FF453A",
    # 设置窗（macOS System Settings 风）
    "win_bg": "#1E1E20",      # 设置窗窗口底（深灰）
    "group": "#2A2A2E",       # 分组卡片底
    "group_line": "#3A3A3C",  # 组内行分割线
    "entry_bg": "#232326",    # 输入框底
    "entry_border": "#3E3E42",# 输入框边框
    "combo_bg": "#232326",    # 下拉底
}
KEY = "#010203"               # 抠色（两主题共用）


def system_is_dark() -> bool:
    """检测 Windows 系统主题：AppsUseLightTheme=0 → 深色。"""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return v == 0
        finally:
            winreg.CloseKey(k)
    except OSError:
        return False


def get_palette(theme: str) -> dict:
    """按配置（system/light/dark）返回配色字典。"""
    if theme == "dark":
        return DARK
    if theme == "light":
        return LIGHT
    return DARK if system_is_dark() else LIGHT

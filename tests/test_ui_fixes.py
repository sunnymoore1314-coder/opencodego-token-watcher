"""UI 修复（2026-08-13）：radio 值比较 / 状态栏两行 / 透明度同步。"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import theme
from src.ui import settings as S
from src.ui.window import UsageWindow


class TestRadioValue(unittest.TestCase):
    """radio 选中判断：StringVar 值比较（修复 bool(非空串) 恒选中 bug）。"""

    def _mk(self, kind="radio", value=None, var_val="dark"):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        var = tk.StringVar(value=var_val)
        ctl = S.AppleControl(root, "深色", var, theme.DARK, S.FONT_LABEL,
                             w=100, h=26, kind=kind, value=value)
        root.update()
        return root, var, ctl

    def test_radio_matching_value_selected(self):
        root, var, ctl = self._mk(value="dark", var_val="dark")
        items = ctl.find_all()
        # 选中药丸应有 today 色填充矩形（fill 使用 today）
        fills = [ctl.itemcget(i, "fill") for i in items]
        self.assertIn(theme.DARK["today"], fills)
        root.destroy()

    def test_radio_nonmatching_not_selected(self):
        root, var, ctl = self._mk(value="light", var_val="dark")
        items = ctl.find_all()
        fills = [ctl.itemcget(i, "fill") for i in items]
        self.assertNotIn(theme.DARK["today"], fills)
        root.destroy()

    def test_toggle_sets_value(self):
        root, var, ctl = self._mk(value="light", var_val="dark")
        ctl._toggle()
        self.assertEqual(var.get(), "light")
        root.destroy()

    def test_check_still_boolean(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        var = tk.BooleanVar(value=False)
        ctl = S.AppleControl(root, "开关", var, theme.DARK, S.FONT_LABEL,
                             w=100, h=24, kind="check")
        root.update()
        ctl._toggle()
        self.assertTrue(var.get())
        root.destroy()


class TestStatusLines(unittest.TestCase):
    """状态栏两行：同步行 + 提示行分离。"""

    def _win(self):
        with mock.patch.object(UsageWindow, "_init_tray"):
            w = UsageWindow.__new__(UsageWindow)
        w.last_error = None
        w.by_day = {"2026-08-13": object()}
        w._sync_time = "12:00"
        w._refresh_ms = 60000
        w._cloud_enabled = True
        w._cloud_err = None
        w._cloud_sync_at = "12:01"
        return w

    def test_two_lines_normal(self):
        w = self._win()
        sync, hint = w._status_lines()
        self.assertIn("12:00", sync)
        self.assertIn("12:01", sync)
        self.assertEqual(hint, "")

    def test_error_goes_to_hint(self):
        w = self._win()
        w._cloud_err = "cookie 过期"
        sync, hint = w._status_lines()
        self.assertIn("cookie 过期", hint)
        self.assertNotIn("cookie 过期", sync)

    def test_last_error_uses_both(self):
        w = self._win()
        w.last_error = "读取失败"
        sync, hint = w._status_lines()
        self.assertIn("读取失败", hint)


class TestAlphaSync(unittest.TestCase):
    """设置窗透明度联动主窗。"""

    def test_preview_alpha_syncs_settings(self):
        s = object.__new__(S.Settings)
        s.master = mock.Mock()
        s.lbl_alpha = mock.Mock()
        with mock.patch.object(S.Settings, "attributes") as m_self_attr:
            s._preview_alpha(0.60)
            s.master.attributes.assert_called_with("-alpha", 0.60)
            m_self_attr.assert_called_with("-alpha", 0.60)
        s.lbl_alpha.config.assert_called_once()


if __name__ == "__main__":
    unittest.main()

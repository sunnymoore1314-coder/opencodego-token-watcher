"""真实 Canvas 边界验收：默认指标、进度条、状态均在卡片内且不重叠。"""
import unittest
from unittest import mock
from src.aggregator import DayStats
from src.ui.settings import H as SETTINGS_H, Settings
from src.ui.window import FIELD_LABELS, UsageWindow


class LayoutTests(unittest.TestCase):
    def verify_layout(self, error):
        with mock.patch('src.ui.window.config.load_config', return_value={}), mock.patch(
                'src.ui.window.opencode_cloud.load_cloud_cache', return_value={"by_day": {}, "last_sync": None}), mock.patch.object(
                UsageWindow, '_init_tray'), mock.patch.object(UsageWindow, '_register_hotkeys'):
            win = UsageWindow()
        try:
            win.withdraw()
            win.by_day = {win.cursor.isoformat(): DayStats(input=100, cache_read=900)}
            win.last_error = error
            win._sync_time = '12:00'
            win.render()
            win.update_idletasks()
            cv = win.canvas
            rows = [cv.bbox(i) for i in cv.find_all()
                    if any(t.startswith('val_') for t in cv.gettags(i))]
            track = cv.bbox('track')
            status = cv.bbox('status')
            self.assertLess(max(b[3] for b in rows), track[1])
            self.assertLess(track[3], status[1])
            self.assertGreaterEqual(status[0], 0)
            self.assertLessEqual(status[2], win._sw)
            hint = cv.bbox('status2')
            if hint:
                self.assertLess(status[3], hint[1])
                self.assertLessEqual(hint[3], win._sh - 4)
            self.assertLessEqual(status[3], win._sh - 4)
        finally:
            for job in win.tk.call('after', 'info'):
                win.after_cancel(job)
            win.destroy()

    def test_default_fields_fit(self):
        self.verify_layout(None)

    def test_missing_database_hint_fits(self):
        self.verify_layout('未找到数据源，请在设置中指定 opencode.db 路径')

    def test_all_metrics_expand_automatically(self):
        cfg = {"window_size": [250, 120], "display_fields": list(FIELD_LABELS)}
        with mock.patch('src.ui.window.config.load_config', return_value=cfg), mock.patch(
                'src.ui.window.opencode_cloud.load_cloud_cache',
                return_value={"by_day": {}, "last_sync": None}), mock.patch.object(
                UsageWindow, '_init_tray'), mock.patch.object(UsageWindow, '_register_hotkeys'):
            win = UsageWindow()
        try:
            win.withdraw()
            win.by_day = {win.cursor.isoformat(): DayStats(input=100, cache_read=900)}
            win._sync_time = '12:00'
            win.render()
            win.update_idletasks()
            cv = win.canvas
            rows = [cv.bbox(i) for i in cv.find_all()
                    if any(t.startswith('val_') for t in cv.gettags(i))]
            self.assertEqual(len(rows), len(FIELD_LABELS))
            self.assertGreater(win._sh, 300)
            self.assertLessEqual(max(b[3] for b in rows), cv.bbox('track')[1])
            self.assertLess(cv.bbox('track')[3], cv.bbox('status')[1])
            self.assertLessEqual(cv.bbox('status')[3], win._sh - 4)
        finally:
            for job in win.tk.call('after', 'info'):
                win.after_cancel(job)
            win.destroy()

    def test_settings_are_visible_without_scroll_viewport(self):
        root = __import__('tkinter').Tk()
        root.withdraw()
        try:
            with mock.patch('src.ui.settings.config.load_config', return_value={}):
                settings = Settings(root)
            settings.withdraw()
            settings.update_idletasks()
            self.assertFalse(hasattr(settings, 'scroll'))
            self.assertLessEqual(max(settings._layout_bottoms), SETTINGS_H - 44 - 62)
            for name in ('scale', 'btn_save', 'btn_cancel', 'entry', 'entry_ws',
                         'entry_cookie', 'btn_dir'):
                self.assertTrue(hasattr(settings, name), name)
            settings.destroy()
        finally:
            root.destroy()

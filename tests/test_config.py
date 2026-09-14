"""配置容错、迁移与原子持久化回归测试。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import config


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "config.json"
        patch = mock.patch.object(config, "get_config_path", return_value=self.path)
        patch.start()
        self.addCleanup(patch.stop)

    def load(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return config.load_config()

    def test_invalid_types_restore_defaults(self):
        data = {"db_path": [], "refresh_interval": "oops", "window_alpha": None,
                "window_pos": "oops", "cloud_cookie": {}, "theme": [],
                "number_format": {}, "autostart": "false", "window_size": ["bad", 10]}
        got = self.load(data)
        for field in data:
            self.assertEqual(got[field], config.default_config()[field], field)

    def test_clamps_ranges(self):
        got = self.load({"window_alpha": 3, "refresh_interval": 0, "window_size": [9999, 1]})
        self.assertEqual(got["window_alpha"], 0.95)
        self.assertEqual(got["refresh_interval"], 1)
        self.assertEqual(got["window_size"], [600, 120])

    def test_migrates_and_filters_display_fields(self):
        got = self.load({"display_fields": ["input", "output", {}, "output", "unknown"]})
        self.assertEqual(got["display_fields"], ["input_total", "output"])
        got = self.load({"display_fields": ["unknown"]})
        self.assertEqual(got["display_fields"], config.default_config()["display_fields"])

    def test_persistence_retains_size_and_tip_state(self):
        data = config.default_config()
        data.update(window_size=[300, 220], window_pos=[-200, 42], tips_shown=True)
        config.save_config(data)
        self.assertEqual(config.load_config(), data)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_nonfinite_numbers_use_defaults(self):
        got = self.load({"window_alpha": float("nan"), "refresh_interval": float("inf")})
        self.assertEqual(got["window_alpha"], 0.78)
        self.assertEqual(got["refresh_interval"], 1)

    def test_replace_failure_keeps_old_file(self):
        self.path.write_text('{"theme":"dark"}', encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                config.save_config(config.default_config())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), {"theme": "dark"})
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.app.runtime_paths import (
    CRASH_LOG_NAME,
    user_data_directory,
    user_log_directory,
    user_settings_path,
    write_crash_log,
)


class RuntimePathTests(unittest.TestCase):
    def test_user_log_directory_uses_local_app_data(self) -> None:
        root = Path(r"C:\Users\tester\AppData\Local")

        self.assertEqual(
            user_log_directory(
                {"LOCALAPPDATA": str(root)},
                platform_name="win32",
            ),
            root / "LiDARLabelTool" / "logs",
        )

        self.assertEqual(
            user_settings_path(
                {"LOCALAPPDATA": str(root)},
                platform_name="win32",
            ),
            root / "LiDARLabelTool" / "settings.ini",
        )

    def test_linux_paths_follow_xdg_directories(self) -> None:
        home = Path("/home/tester")
        env = {
            "XDG_CONFIG_HOME": "/mnt/config",
            "XDG_DATA_HOME": "/mnt/data",
            "XDG_STATE_HOME": "/mnt/state",
        }

        self.assertEqual(
            user_settings_path(env, home=home, platform_name="linux"),
            Path("/mnt/config/LiDARLabelTool/settings.ini"),
        )
        self.assertEqual(
            user_data_directory(env, home=home, platform_name="linux"),
            Path("/mnt/data/LiDARLabelTool"),
        )
        self.assertEqual(
            user_log_directory(env, home=home, platform_name="linux"),
            Path("/mnt/state/LiDARLabelTool/logs"),
        )

    def test_linux_paths_use_xdg_fallbacks(self) -> None:
        home = Path("/home/tester")

        self.assertEqual(
            user_settings_path({}, home=home, platform_name="linux"),
            home / ".config" / "LiDARLabelTool" / "settings.ini",
        )
        self.assertEqual(
            user_data_directory({}, home=home, platform_name="linux"),
            home / ".local" / "share" / "LiDARLabelTool",
        )
        self.assertEqual(
            user_log_directory({}, home=home, platform_name="linux"),
            home / ".local" / "state" / "LiDARLabelTool" / "logs",
        )

    def test_crash_log_falls_back_when_primary_location_is_not_writable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            blocked = root / "blocked"
            blocked.write_text("not a directory", encoding="utf-8")
            fallback = root / "fallback"

            written = write_crash_log(
                "traceback details",
                {"LOCALAPPDATA": str(blocked)},
                fallback_root=fallback,
                platform_name="win32",
            )

            self.assertEqual(written, fallback / "LiDARLabelTool" / CRASH_LOG_NAME)
            self.assertEqual(written.read_text(encoding="utf-8"), "traceback details")

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.app.runtime_paths import (
    CRASH_LOG_NAME,
    user_log_directory,
    write_crash_log,
)


class RuntimePathTests(unittest.TestCase):
    def test_user_log_directory_uses_local_app_data(self) -> None:
        root = Path(r"C:\Users\tester\AppData\Local")

        self.assertEqual(
            user_log_directory({"LOCALAPPDATA": str(root)}),
            root / "LiDARLabelTool" / "logs",
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
            )

            self.assertEqual(written, fallback / "LiDARLabelTool" / CRASH_LOG_NAME)
            self.assertEqual(written.read_text(encoding="utf-8"), "traceback details")

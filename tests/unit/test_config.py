from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from lidar_label_tool.app.config import default_config_path


class ConfigPathTests(unittest.TestCase):
    def test_default_config_path_prefers_pyinstaller_meipass(self) -> None:
        original = getattr(sys, "_MEIPASS", None)
        had_original = hasattr(sys, "_MEIPASS")
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / "configs" / "default.json"
                config.parent.mkdir()
                config.write_text("{}", encoding="utf-8")
                sys._MEIPASS = str(root)  # type: ignore[attr-defined]

                self.assertEqual(default_config_path(), config)
        finally:
            if had_original:
                sys._MEIPASS = original  # type: ignore[attr-defined]
            else:
                try:
                    del sys._MEIPASS  # type: ignore[attr-defined]
                except AttributeError:
                    pass

    def test_frozen_config_does_not_fall_back_to_current_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as bundle_directory, tempfile.TemporaryDirectory() as cwd:
            bundle_root = Path(bundle_directory)
            cwd_config = Path(cwd) / "configs" / "default.json"
            cwd_config.parent.mkdir()
            cwd_config.write_text("{}", encoding="utf-8")
            with patch.object(sys, "_MEIPASS", str(bundle_root), create=True), patch(
                "pathlib.Path.cwd", return_value=Path(cwd)
            ):
                self.assertEqual(
                    default_config_path(),
                    bundle_root / "configs" / "default.json",
                )

    def test_default_config_path_supports_regular_wheel_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)
            installed = (
                prefix
                / "share"
                / "lidar-label-tool"
                / "configs"
                / "default.json"
            )
            installed.parent.mkdir(parents=True)
            installed.write_text("{}", encoding="utf-8")

            with patch.object(sys, "prefix", str(prefix)):
                self.assertEqual(default_config_path(), installed)


if __name__ == "__main__":
    unittest.main()

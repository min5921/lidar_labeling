from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.ui.main_window import MainWindow
from tests.fixture_builders import create_v2_dataset


class V2MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_constructs_profile_scoped_editor_without_loading_inactive_lidar(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 GUI 데이터"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)

            with patch.object(MainWindow, "_request_frame") as request_frame:
                window = MainWindow(
                    root,
                    default_config_path(),
                    profile_id="aeva_profile",
                )

            self.assertIsInstance(window.adapter, DeviceCentricV2Adapter)
            self.assertEqual(window.index.profile_id, "aeva_profile")
            self.assertEqual(window.index.lidar_ids, ("aeva",))
            self.assertEqual(tuple(window.sensor_checks), ("aeva",))
            self.assertEqual(
                [window.new_class_combo.itemText(index) for index in range(window.new_class_combo.count())],
                ["car"],
            )
            request_frame.assert_called_once_with("000000")
            window.close()


if __name__ == "__main__":
    unittest.main()

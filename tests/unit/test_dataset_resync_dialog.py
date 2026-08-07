from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication

from lidar_label_tool.services.dataset_resync_v2 import (
    DatasetResyncRequest,
    analyze_dataset_resync_v2,
)
from lidar_label_tool.ui.dataset_resync_dialog import DatasetResyncV2Dialog
from tests.fixture_builders import create_v2_dataset


class DatasetResyncV2DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_requires_a_fresh_analysis_before_apply(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            dialog = DatasetResyncV2Dialog(root)

            self.assertEqual(dialog.profile_combo.currentData(), "aeva_profile")
            self.assertEqual(dialog.method_combo.currentData(), "timestamp_nearest")
            self.assertFalse(dialog.apply_button.isEnabled())

            analysis = analyze_dataset_resync_v2(
                DatasetResyncRequest(root, "aeva_profile")
            )
            dialog._on_analysis_completed(analysis)
            self.assertTrue(dialog.apply_button.isEnabled())
            self.assertIn("LiDAR frame/sample/path binding 변경: 0", dialog.summary.toPlainText())

            dialog.method_combo.setCurrentIndex(0)
            self.assertIsNone(dialog.analysis)
            self.assertFalse(dialog.apply_button.isEnabled())
            dialog.close()


if __name__ == "__main__":
    unittest.main()

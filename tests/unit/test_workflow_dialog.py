from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from lidar_label_tool.ui.workflow_dialog import OneChipConversionDialog


class WorkflowDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_resync_does_not_require_calibration_folder(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            dataset = root / "dataset"
            source.mkdir()
            dataset.mkdir()
            (dataset / "dataset.json").write_text("{}", encoding="utf-8")
            with patch(
                "lidar_label_tool.ui.workflow_dialog.user_settings_path",
                return_value=root / "settings" / "settings.ini",
            ):
                dialog = OneChipConversionDialog(None, "resync")
            dialog.source_row.edit.setText(str(source))
            dialog.calibration_row.edit.clear()
            dialog.output_row.edit.setText(str(dataset))

            request = dialog._request()

            self.assertEqual(request.mode, "resync")
            self.assertEqual(request.output, dataset)
            dialog.close()

    def test_convert_rejects_empty_source_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            calibration = root / "calibration"
            calibration.mkdir()
            with patch(
                "lidar_label_tool.ui.workflow_dialog.user_settings_path",
                return_value=root / "settings" / "settings.ini",
            ):
                dialog = OneChipConversionDialog(None, "convert")
            dialog.source_row.edit.clear()
            dialog.calibration_row.edit.setText(str(calibration))
            dialog.output_row.edit.setText(str(root / "output"))

            with self.assertRaisesRegex(ValueError, "원본 데이터 루트"):
                dialog._request()
            dialog.close()


if __name__ == "__main__":
    unittest.main()

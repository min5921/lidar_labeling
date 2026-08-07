from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from lidar_label_tool.services.dataset_discovery import discover_dataset
from lidar_label_tool.services.dataset_setup import analyze_generic_dataset
from lidar_label_tool.ui.dataset_setup_dialog import DatasetSetupDialog


class DatasetSetupDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_requires_explicit_point_columns_and_coordinate_confirmation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터"
            _write(root / "AEVA" / "000000.bin", b"\x00" * 16)
            discovery = discover_dataset(root)
            dialog = DatasetSetupDialog(
                root,
                _config(),
                discovery_result=discovery,
            )

            self.assertFalse(dialog.apply_button.isEnabled())
            dialog.lidar_table.item(0, 4).setText("x,y,z,intensity")
            self.assertFalse(dialog.apply_button.isEnabled())
            dialog.coordinate_confirm.setChecked(True)

            self.assertTrue(dialog.apply_button.isEnabled())
            self.assertFalse(dialog.create_button.isEnabled())
            request = dialog.build_request()
            self.assertEqual(len(request.lidars), 1)
            self.assertEqual(request.lidars[0].point_columns, ("x", "y", "z", "intensity"))
            self.assertEqual(request.lidars[0].sync_method, "lidar_only")
            self.assertFalse((root / "dataset.json").exists())

            analysis = analyze_generic_dataset(request)
            dialog._on_analysis_completed(analysis)

            self.assertTrue(dialog.create_button.isEnabled())
            self.assertIn("LiDAR 1", dialog.status_label.text())
            self.assertFalse((root / "dataset.json").exists())

            request_generation = dialog._configuration_generation
            stale_result: Future[object] = Future()
            stale_result.set_result(analysis)
            dialog._set_busy(True)
            self.assertFalse(dialog.lidar_table.isEnabled())
            dialog.lidar_table.item(0, 4).setText("x,y,z")
            dialog._finish_future("analysis", stale_result, request_generation)
            self.app.processEvents()

            self.assertIsNone(dialog.analysis)
            self.assertFalse(dialog.create_button.isEnabled())
            self.assertIn("폐기", dialog.status_label.text())
            dialog.close()

    def test_camera_is_single_select_and_timestamp_requires_explicit_tables(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root / "A" / "000000.bin", b"\x00" * 16)
            _write(root / "B" / "000000.bin", b"\x00" * 16)
            _write(root / "CAM_A" / "000000.jpg", b"image")
            _write(root / "CAM_B" / "000000.jpg", b"image")
            _write(
                root / "timestamps.csv",
                b"sample_id,timestamp_ns\n000000,1\n",
            )
            dialog = DatasetSetupDialog(
                root,
                _config(),
                discovery_result=discover_dataset(root),
            )
            dialog.lidar_table.item(0, 4).setText("x,y,z,intensity")
            dialog.lidar_table.item(1, 0).setCheckState(Qt.CheckState.Checked)
            dialog.lidar_table.item(1, 4).setText("x,y,z,intensity")
            dialog.coordinate_confirm.setChecked(True)
            dialog.camera_combo.setCurrentIndex(1)
            self.assertEqual(dialog.sync_method_combo.currentData(), "exact_stem")
            dialog.sync_method_combo.setCurrentIndex(2)

            self.assertFalse(dialog.apply_button.isEnabled())
            for row in range(dialog.lidar_table.rowCount()):
                combo = dialog.lidar_table.cellWidget(row, 5)
                self.assertIsInstance(combo, QComboBox)
                assert isinstance(combo, QComboBox)
                combo.setCurrentIndex(1)
            dialog.camera_timestamp_combo.setCurrentIndex(1)
            dialog.value_column_edit.setText("timestamp_ns")
            dialog._update_apply_enabled()

            self.assertTrue(dialog.apply_button.isEnabled())
            request = dialog.build_request()
            self.assertEqual(len(request.lidars), 2)
            self.assertIsNotNone(request.camera)
            self.assertTrue(all(item.timestamp is not None for item in request.lidars))
            dialog.close()


def _config() -> dict[str, object]:
    return {
        "classes": [
            {
                "name": "Car",
                "color": "#00D084",
                "default_size": [4.2, 1.8, 1.6],
            }
        ],
        "source_class_mappings": {},
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication

from lidar_label_tool.services.dataset_profile_add_v2 import (
    analyze_dataset_profile_add_v2,
)
from lidar_label_tool.ui.dataset_profile_add_dialog import DatasetProfileAddDialog
from tests.fixture_builders import create_v2_dataset


class DatasetProfileAddDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_prefills_metadata_and_existing_camera_clock_then_requires_analysis(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)
            _add_lidar_points_source(root)

            dialog = DatasetProfileAddDialog(root)

            self.assertEqual(dialog.lidar_combo.count(), 1)
            self.assertEqual(dialog.sensor_id_edit.text(), "lidar_points")
            self.assertEqual(
                dialog.point_columns_edit.text(),
                "x,y,z,intensity,velocity",
            )
            self.assertEqual(dialog.timestamp_combo.currentData(), "timestamps/LIDAR_POINTS.csv")
            self.assertEqual(dialog.sample_column_edit.text(), "sample_id")
            self.assertEqual(dialog.value_column_edit.text(), "bag_time_ns")
            self.assertEqual(dialog.unit_combo.currentText(), "ns")
            self.assertEqual(dialog.clock_domain_edit.text(), "bag")
            self.assertFalse(dialog.analysis_button.isEnabled())
            self.assertFalse(dialog.add_button.isEnabled())

            dialog.coordinate_confirm.setChecked(True)
            self.assertTrue(dialog.analysis_button.isEnabled())
            request = dialog.build_request()
            analysis = analyze_dataset_profile_add_v2(request)
            dialog._on_analysis_completed(analysis)

            self.assertTrue(dialog.add_button.isEnabled())
            self.assertIn("camera matched 2", dialog.status_label.text())
            dialog.point_columns_edit.setText("x,y,z")
            self.assertIsNone(dialog.analysis)
            self.assertFalse(dialog.add_button.isEnabled())
            dialog.close()


def _add_lidar_points_source(root: Path) -> None:
    lidar_root = root / "sensors" / "lidar" / "LIDAR_POINTS" / "frames"
    lidar_root.mkdir(parents=True)
    for number in range(2):
        np.array([[1, 2, 3, 0.5, 4]], dtype="<f4").tofile(
            lidar_root / f"{number:06d}.bin"
        )
    (root / "timestamps" / "LIDAR_POINTS.csv").write_text(
        "sample_id,bag_time_ns\n000000,1000000\n000001,1000100\n",
        encoding="utf-8",
    )
    metadata_root = root / "metadata"
    metadata_root.mkdir(exist_ok=True)
    (metadata_root / "LIDAR_POINTS.json").write_text(
        json.dumps(
            {
                "sensor_id": "LIDAR_POINTS",
                "point_columns": ["x", "y", "z", "intensity", "velocity"],
                "output_dtype": "float32",
                "output_byte_order": "little-endian",
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()

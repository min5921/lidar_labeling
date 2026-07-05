from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.workers.frame_loader import load_frame_payload


class DeviceCentricAdapterTests(unittest.TestCase):
    def test_numbered_device_folders_and_lidar_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "schema_version": "1.0",
                "dataset_id": "device_test",
                "layout": "device_centric",
                "reference_frame": "vehicle",
                "primary_lidar": "TOP",
                "sensors": [
                    {
                        "id": "TOP",
                        "type": "lidar",
                        "coordinate_frame": "vehicle",
                        "data_patterns": {
                            "return1": "sensors/lidar/TOP/return1/{sample_id}.bin"
                        },
                        "point_columns": ["x", "y", "z", "intensity"],
                        "point_dtype": "float32",
                        "byte_order": "little-endian",
                    },
                    {
                        "id": "FRONT",
                        "type": "lidar",
                        "coordinate_frame": "lidar:FRONT",
                        "data_patterns": {
                            "return1": "sensors/lidar/FRONT/return1/{sample_id}.bin"
                        },
                        "point_columns": ["x", "y", "z", "intensity"],
                        "point_dtype": "float32",
                        "byte_order": "little-endian",
                    },
                    {
                        "id": "CAM_FRONT",
                        "type": "camera",
                        "coordinate_frame": "camera:FRONT",
                        "data_patterns": {
                            "image": "sensors/camera/CAM_FRONT/images/{sample_id}.jpg"
                        },
                    },
                ],
                "synchronization": {"mode": "exact_stem"},
                "calibration_path": "calibration/calibration.json",
            }
            calibration = {
                "schema_version": "1.0",
                "reference_frame": "vehicle",
                "lidars": {
                    "FRONT": {
                        "T_reference_sensor": [
                            [1, 0, 0, 1],
                            [0, 1, 0, 2],
                            [0, 0, 1, 3],
                            [0, 0, 0, 1],
                        ]
                    }
                },
            }
            (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
            calibration_path = root / "calibration" / "calibration.json"
            calibration_path.parent.mkdir(parents=True)
            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            for sensor in ("TOP", "FRONT"):
                folder = root / "sensors" / "lidar" / sensor / "return1"
                folder.mkdir(parents=True)
                for sample_id in ("0000", "0001"):
                    np.array([[0, 0, 0, 5]], dtype="<f4").tofile(
                        folder / f"{sample_id}.bin"
                    )
            image_folder = root / "sensors" / "camera" / "CAM_FRONT" / "images"
            image_folder.mkdir(parents=True)
            (image_folder / "0000.jpg").write_bytes(b"placeholder")

            adapter = open_dataset_adapter(root)
            self.assertIsInstance(adapter, DeviceCentricAdapter)
            index = adapter.scan()
            self.assertEqual(index.frame_ids, ("0000", "0001"))
            source = adapter.load_source_frame("0000")
            self.assertEqual(set(source.point_cloud_paths), {"TOP", "FRONT"})
            self.assertEqual(set(source.image_paths), {"CAM_FRONT"})
            self.assertEqual(source.source_label_paths, {})
            transformed = adapter.load_cloud_from_source(source, "FRONT")
            np.testing.assert_allclose(transformed.xyz, [[1, 2, 3]])
            self.assertEqual(transformed.source_frame, "vehicle")

    def test_merged_reference_cloud_survives_missing_optional_raw_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "schema_version": "1.0",
                "dataset_id": "merged_with_optional_raw",
                "layout": "device_centric",
                "reference_frame": "vehicle",
                "primary_lidar": "MERGED",
                "sensors": [
                    {
                        "id": "MERGED",
                        "type": "lidar",
                        "coordinate_frame": "vehicle",
                        "data_patterns": {
                            "return1": "sensors/lidar/MERGED/{sample_id}.bin"
                        },
                        "point_columns": ["x", "y", "z"],
                        "point_dtype": "float32",
                    },
                    {
                        "id": "RAW_FRONT",
                        "type": "lidar",
                        "coordinate_frame": "lidar:FRONT",
                        "data_patterns": {
                            "return1": "sensors/lidar/RAW_FRONT/{sample_id}.bin"
                        },
                        "point_columns": ["x", "y", "z"],
                        "point_dtype": "float32",
                    },
                ],
                "synchronization": {"mode": "exact_stem"},
                "calibration_path": "calibration/missing.json",
            }
            (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
            for sensor in ("MERGED", "RAW_FRONT"):
                folder = root / "sensors" / "lidar" / sensor
                folder.mkdir(parents=True)
                np.array([[1, 2, 3]], dtype="<f4").tofile(folder / "0000.bin")

            adapter = DeviceCentricAdapter(root)
            index = adapter.scan()
            source = adapter.load_source_frame(index.frame_ids[0])

            self.assertEqual(set(source.point_cloud_paths), {"MERGED"})
            self.assertEqual(source.metadata["sensor_status"]["MERGED"], "not_required")
            self.assertEqual(source.metadata["sensor_status"]["RAW_FRONT"], "missing")
            cloud = adapter.load_cloud_from_source(source, "MERGED")
            np.testing.assert_allclose(cloud.xyz, [[1, 2, 3]])

    def test_declared_missing_return_reaches_loader_for_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "schema_version": "1.0",
                "dataset_id": "missing_return",
                "layout": "device_centric",
                "reference_frame": "vehicle",
                "primary_lidar": "MERGED",
                "sensors": [
                    {
                        "id": "MERGED",
                        "type": "lidar",
                        "coordinate_frame": "vehicle",
                        "data_patterns": {
                            "return1": "sensors/lidar/MERGED/r1/{sample_id}.bin",
                            "return2": "sensors/lidar/MERGED/r2/{sample_id}.bin",
                        },
                        "point_columns": ["x", "y", "z"],
                        "point_dtype": "float32",
                    }
                ],
                "synchronization": {"mode": "exact_stem"},
            }
            (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
            return1 = root / "sensors" / "lidar" / "MERGED" / "r1"
            return1.mkdir(parents=True)
            np.array([[1, 2, 3]], dtype="<f4").tofile(return1 / "0000.bin")

            adapter = DeviceCentricAdapter(root)
            adapter.scan()
            source = adapter.load_source_frame("0000")

            self.assertEqual(len(source.point_cloud_paths["MERGED"]), 2)
            self.assertFalse(source.point_cloud_paths["MERGED"][1].exists())
            with self.assertRaises(FileNotFoundError):
                adapter.load_cloud_from_source(source, "MERGED", "2")
            payload = load_frame_payload(adapter, WaymoLabelImporter({}), "0000")
            self.assertEqual(len(payload.clouds["MERGED"]), 1)
            self.assertIn("MERGED:return2", payload.sensor_errors)
            self.assertIn("FileNotFoundError", payload.sensor_errors["MERGED:return2"])


if __name__ == "__main__":
    unittest.main()

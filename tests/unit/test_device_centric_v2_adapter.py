from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.domain.label_identity_v2 import (
    frame_record_sha256,
    lidar_binding_sha256,
)
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.services.dataset_discovery import discover_dataset
from lidar_label_tool.services.dataset_setup import (
    DatasetSetupRequest,
    LidarSetup,
    create_generic_dataset,
    taxonomy_from_config,
)
from lidar_label_tool.services.dataset_v2_validation import validate_dataset_v2
from tests.fixture_builders import create_v2_dataset


class DeviceCentricV2AdapterTests(unittest.TestCase):
    def test_factory_opens_default_profile_and_loads_only_active_lidar(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터 세트"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)

            adapter = open_dataset_adapter(root)
            self.assertIsInstance(adapter, DeviceCentricV2Adapter)
            index = adapter.scan()
            source = adapter.load_source_frame("000000")
            cloud = adapter.load_cloud_from_source(source, "aeva")

            self.assertEqual(index.profile_id, "aeva_profile")
            self.assertEqual(index.lidar_ids, ("aeva",))
            self.assertEqual(index.camera_ids, ("head_camera",))
            self.assertEqual(tuple(source.point_cloud_paths), ("aeva",))
            self.assertEqual(cloud.point_count, 1)
            self.assertEqual(source.metadata["profile_id"], "aeva_profile")
            self.assertEqual(
                source.metadata["lidar_binding_sha256"],
                lidar_binding_sha256(adapter.frame_record("000000")),
            )
            self.assertEqual(
                source.metadata["frame_record_sha256"],
                frame_record_sha256(adapter.frame_record("000000")),
            )

    def test_missing_camera_does_not_block_lidar_loading(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            (root / "sensors" / "camera" / "HEAD_CAMERA" / "images" / "000000.jpg").unlink()

            adapter = DeviceCentricV2Adapter(root)
            source = adapter.load_source_frame("000000")

            self.assertEqual(source.image_paths, {})
            self.assertEqual(
                adapter.load_cloud_from_source(source, "aeva").point_count,
                1,
            )

    def test_invalid_calibration_disables_projection_without_blocking_lidar(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = create_v2_dataset(root, with_camera=True)
            calibration_path = root / "generations" / "generation-000001" / "calibration.json"
            calibration = {
                "schema_version": "1.0",
                "reference_frame": "lidar:AEVA",
                "lidars": {
                    "aeva": {"T_reference_sensor": _identity_matrix()},
                },
                "cameras": {
                    "head_camera": {
                        "intrinsic": [[100.0, 0.0, 50.0], [0.0, 100.0, 40.0], [0.0, 0.0, 1.0]],
                        "T_camera_reference": _identity_matrix(),
                        "image_size": [100, 80],
                        "distortion_model": "none",
                    }
                },
            }
            calibration_path.write_text(
                json.dumps(calibration),
                encoding="utf-8",
            )
            profile = manifest["profiles"][0]  # type: ignore[index]
            profile["camera"] = {  # type: ignore[index]
                "camera_id": "head_camera",
                "mode": "calibrated",
                "calibration_path": "generations/generation-000001/calibration.json",
                "calibration_sha256": hashlib.sha256(calibration_path.read_bytes()).hexdigest(),
            }
            (root / "dataset.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            calibrated = DeviceCentricV2Adapter(root)
            self.assertEqual(calibrated.camera_calibration_count, 1)

            calibration_path.write_text("{}", encoding="utf-8")
            adapter = DeviceCentricV2Adapter(root)
            source = adapter.load_source_frame("000000")
            report = validate_dataset_v2(root)

            self.assertEqual(adapter.camera_calibration_count, 0)
            self.assertEqual(adapter.load_cloud_from_source(source, "aeva").point_count, 1)
            self.assertIn(
                "calibration_hash_mismatch",
                {issue.code for issue in report.issues},
            )

    def test_profiles_with_same_frame_id_never_mix_lidars(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            config_root = Path(directory) / "workspace" / "config"
            _point(source / "A" / "000000.bin", 1.0)
            _point(source / "B" / "000000.bin", 2.0)
            discovery = discover_dataset(source)
            setups = []
            for candidate in discovery.lidars:
                sensor_id = candidate.display_name.casefold()
                setups.append(
                    LidarSetup(
                        candidate=candidate,
                        sensor_id=sensor_id,
                        display_name=candidate.display_name,
                        coordinate_frame=f"lidar:{candidate.display_name}",
                        point_columns=("x", "y", "z", "intensity"),
                        profile_id=f"{sensor_id}_profile",
                        profile_display_name=candidate.display_name,
                        sync_method="lidar_only",
                    )
                )
            create_generic_dataset(
                DatasetSetupRequest(
                    source_root=source,
                    config_root=config_root,
                    display_name="profiles",
                    dataset_id="ds_profile_isolation",
                    lidars=tuple(setups),
                    taxonomy=_taxonomy(),
                    coordinate_system_confirmed=True,
                    default_profile_id="a_profile",
                )
            )

            adapter_a = DeviceCentricV2Adapter(config_root, "a_profile")
            adapter_b = DeviceCentricV2Adapter(config_root, "b_profile")
            frame_a = adapter_a.load_source_frame("000000")
            frame_b = adapter_b.load_source_frame("000000")

            self.assertEqual(tuple(frame_a.point_cloud_paths), ("a",))
            self.assertEqual(tuple(frame_b.point_cloud_paths), ("b",))
            self.assertNotEqual(
                frame_a.point_cloud_paths["a"][0],
                frame_b.point_cloud_paths["b"][0],
            )
            self.assertEqual(adapter_a.load_cloud_from_source(frame_a, "a").xyz[0, 0], 1.0)
            self.assertEqual(adapter_b.load_cloud_from_source(frame_b, "b").xyz[0, 0], 2.0)
            with self.assertRaises(KeyError):
                adapter_a.load_cloud_from_source(frame_a, "b")


def _point(path: Path, x: float) -> None:
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<ffff", x, 0.0, 0.0, 1.0))


def _identity_matrix() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _taxonomy() -> dict[str, object]:
    return taxonomy_from_config(
        {
            "classes": [
                {
                    "name": "Car",
                    "color": "#00D084",
                    "default_size": [4.2, 1.8, 1.6],
                }
            ],
            "source_class_mappings": {},
        }
    )


if __name__ == "__main__":
    unittest.main()

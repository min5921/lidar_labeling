from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.dataset_v2 import load_dataset_manifest_v2
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.dataset_discovery import discover_dataset
from lidar_label_tool.services.dataset_profile_add_v2 import (
    DatasetProfileAddConflictError,
    DatasetProfileAddRequest,
    add_dataset_profile_v2,
    analyze_dataset_profile_add_v2,
)
from lidar_label_tool.services.dataset_setup import CameraSetup, LidarSetup, TimestampSetup
from lidar_label_tool.services.dataset_v2_validation import validate_dataset_v2
from tests.fixture_builders import create_v2_dataset


class DatasetProfileAddV2Tests(unittest.TestCase):
    def test_adds_profile_in_new_generation_and_preserves_existing_label(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터 세트 01"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)
            _add_lidar_points_source(root)
            old_adapter = DeviceCentricV2Adapter(root, "aeva_profile")
            old_repository = V2LabelRepository.for_sidecar(old_adapter)
            old_repository.save(_new_label(old_adapter))
            label_before = old_repository.path_for("000000").read_bytes()
            source_before = _source_hashes(root)
            request = _request(root)

            analysis = analyze_dataset_profile_add_v2(request)

            self.assertEqual(analysis.current_manifest_revision, 1)
            self.assertEqual(analysis.next_manifest_revision, 2)
            self.assertEqual(analysis.existing_label_count, 1)
            self.assertEqual(analysis.qa.lidar_frame_count, 2)
            self.assertEqual(analysis.qa.matched_camera_count, 2)
            self.assertFalse((root / "generations" / "generation-000002").exists())
            self.assertEqual(load_dataset_manifest_v2(root).manifest_revision, 1)

            result = add_dataset_profile_v2(
                replace(
                    request,
                    expected_manifest_sha256=analysis.manifest_sha256,
                    expected_source_inventory_sha256=(
                        analysis.source_inventory_sha256
                    ),
                )
            )

            manifest = load_dataset_manifest_v2(root)
            self.assertEqual(result.manifest_revision, 2)
            self.assertEqual(manifest.dataset_id, "ds_fixture_v2")
            self.assertEqual(manifest.default_profile_id, "aeva_profile")
            self.assertEqual({item.id for item in manifest.lidars}, {"aeva", "lidar_points"})
            self.assertEqual(
                {item.id for item in manifest.profiles},
                {"aeva_profile", "lidar_points_profile"},
            )
            self.assertTrue((root / "generations" / "generation-000001").is_dir())
            self.assertTrue((root / "generations" / "generation-000002").is_dir())
            self.assertTrue(validate_dataset_v2(root).is_valid)
            self.assertEqual(_source_hashes(root), source_before)
            self.assertEqual(old_repository.path_for("000000").read_bytes(), label_before)

            refreshed_old = V2LabelRepository.for_sidecar(
                DeviceCentricV2Adapter(root, "aeva_profile")
            )
            self.assertEqual(refreshed_old.load("000000").revision, 1)
            added_adapter = DeviceCentricV2Adapter(root, "lidar_points_profile")
            self.assertEqual(added_adapter.scan().frame_ids, ("000000", "000001"))
            self.assertEqual(added_adapter.active_lidar.id, "lidar_points")

    def test_source_change_after_analysis_preserves_manifest_and_generation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            _add_lidar_points_source(root)
            request = _request(root)
            manifest_before = (root / "dataset.json").read_bytes()
            analysis = analyze_dataset_profile_add_v2(request)
            (root / "timestamps" / "LIDAR_POINTS.csv").write_text(
                "sample_id,bag_time_ns\n000000,5\n000001,105\n",
                encoding="utf-8",
            )

            with self.assertRaises(DatasetProfileAddConflictError):
                add_dataset_profile_v2(
                    replace(
                        request,
                        expected_manifest_sha256=analysis.manifest_sha256,
                        expected_source_inventory_sha256=(
                            analysis.source_inventory_sha256
                        ),
                    )
                )

            self.assertEqual((root / "dataset.json").read_bytes(), manifest_before)
            self.assertFalse((root / "generations" / "generation-000002").exists())

    def test_manifest_replace_failure_rolls_back_new_generation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            _add_lidar_points_source(root)
            request = _request(root)
            analysis = analyze_dataset_profile_add_v2(request)
            manifest_path = root / "dataset.json"
            manifest_before = manifest_path.read_bytes()
            real_replace = os.replace

            def fail_manifest_replace(
                source: str | os.PathLike[str],
                target: str | os.PathLike[str],
            ) -> None:
                if Path(target).resolve() == manifest_path.resolve():
                    raise OSError("injected manifest replace failure")
                real_replace(source, target)

            with patch(
                "lidar_label_tool.services.dataset_profile_add_v2.os.replace",
                side_effect=fail_manifest_replace,
            ):
                with self.assertRaises(OSError):
                    add_dataset_profile_v2(
                        replace(
                            request,
                            expected_manifest_sha256=analysis.manifest_sha256,
                            expected_source_inventory_sha256=(
                                analysis.source_inventory_sha256
                            ),
                        )
                    )

            self.assertEqual(manifest_path.read_bytes(), manifest_before)
            self.assertFalse((root / "generations" / "generation-000002").exists())


def _request(root: Path) -> DatasetProfileAddRequest:
    discovery = discover_dataset(root)
    lidar = next(item for item in discovery.lidars if item.suggested_id == "lidar_points")
    camera = next(item for item in discovery.cameras if item.suggested_id == "head_camera")
    timestamp = TimestampSetup(
        relative_path="timestamps/LIDAR_POINTS.csv",
        sample_id_column="sample_id",
        value_column="bag_time_ns",
        unit="ns",
        clock_domain="bag",
    )
    return DatasetProfileAddRequest(
        config_root=root,
        lidar=LidarSetup(
            candidate=lidar,
            sensor_id="lidar_points",
            display_name="LIDAR_POINTS",
            coordinate_frame="lidar:LIDAR_POINTS",
            point_columns=("x", "y", "z", "intensity", "velocity"),
            profile_id="lidar_points_profile",
            profile_display_name="LIDAR_POINTS 라벨링",
            sync_method="timestamp_nearest",
            tolerance_ns=50,
            timestamp=timestamp,
        ),
        camera=CameraSetup(
            candidate=camera,
            sensor_id="head_camera",
            display_name="Head camera",
            coordinate_frame="camera:HEAD_CAMERA",
        ),
        coordinate_system_confirmed=True,
    )


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


def _new_label(adapter: DeviceCentricV2Adapter):
    return WaymoLabelImporter({}, source_format="device_centric_v2").import_laser_labels(
        adapter.load_source_frame("000000")
    )


def _source_hashes(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for folder in ("sensors", "timestamps", "metadata"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file():
                result[path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return result


if __name__ == "__main__":
    unittest.main()

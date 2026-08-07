from __future__ import annotations

import hashlib
from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.dataset_discovery import SensorCandidate, discover_dataset
from lidar_label_tool.services.dataset_preflight import validate_dataset
from lidar_label_tool.services.dataset_resync_v2 import (
    DatasetResyncRequest,
    analyze_dataset_resync_v2,
    resynchronize_dataset_v2,
)
from lidar_label_tool.services.dataset_setup import (
    CameraSetup,
    DatasetSetupRequest,
    LidarSetup,
    TimestampSetup,
    create_generic_dataset,
    taxonomy_from_config,
)


class GenericDatasetV2IntegrationTests(unittest.TestCase):
    def test_multi_lidar_profiles_keep_labels_isolated_across_resync(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "한글 원본 데이터 01"
            config_root = root / "외부 작업 공간" / "구성 파일"
            for sample_id, x in (("000000", 1.0), ("000001", 1.1)):
                _point(source / "lidar" / "A" / f"{sample_id}.bin", x)
            for sample_id, x in (("000000", 2.0), ("000001", 2.1)):
                _point(source / "lidar" / "B" / f"{sample_id}.bin", x)
            for sample_id in ("000000", "000001"):
                _image(source / "camera" / "HEAD" / f"{sample_id}.jpg")
            _timestamp(
                source / "timestamps" / "A.csv",
                (("000000", 100), ("000001", 200)),
            )
            _timestamp(
                source / "timestamps" / "B.csv",
                (("000000", 110), ("000001", 210)),
            )
            camera_timestamp = source / "timestamps" / "HEAD.csv"
            _timestamp(
                camera_timestamp,
                (("000000", 105), ("000001", 205)),
            )
            discovery = discover_dataset(source)
            candidates = {Path(item.directory).name: item for item in discovery.lidars}
            camera_candidate = discovery.cameras[0]
            timestamp = lambda name: TimestampSetup(  # noqa: E731 - concise fixture
                relative_path=f"timestamps/{name}.csv",
                sample_id_column="sample_id",
                value_column="timestamp_ns",
                unit="ns",
                clock_domain="bag",
            )
            setup = create_generic_dataset(
                DatasetSetupRequest(
                    source_root=source,
                    config_root=config_root,
                    display_name="두 LiDAR 독립 라벨링",
                    dataset_id="ds_generic_integration",
                    lidars=(
                        _lidar_setup(candidates["A"], "a", timestamp("A")),
                        _lidar_setup(candidates["B"], "b", timestamp("B")),
                    ),
                    camera=CameraSetup(
                        candidate=camera_candidate,
                        sensor_id="head_camera",
                        display_name="Head camera",
                        coordinate_frame="camera:HEAD",
                        timestamp=timestamp("HEAD"),
                    ),
                    taxonomy=_taxonomy(),
                    coordinate_system_confirmed=True,
                    default_profile_id="a_profile",
                )
            )
            self.assertTrue(setup.validation.is_valid, setup.validation.issues)
            self.assertFalse((source / "dataset.json").exists())

            adapter_a = DeviceCentricV2Adapter(config_root, "a_profile")
            adapter_b = DeviceCentricV2Adapter(config_root, "b_profile")
            repository_a = V2LabelRepository.for_sidecar(adapter_a)
            repository_b = V2LabelRepository.for_sidecar(adapter_b)
            importer = WaymoLabelImporter({}, "device_centric_v2")
            repository_a.save(
                importer.import_laser_labels(adapter_a.load_source_frame("000000"))
            )
            repository_b.save(
                importer.import_laser_labels(adapter_b.load_source_frame("000000"))
            )
            self.assertNotEqual(
                repository_a.path_for("000000"),
                repository_b.path_for("000000"),
            )

            _timestamp(
                camera_timestamp,
                (("000000", 10_000), ("000001", 20_000)),
            )
            source_before_resync = _tree_hashes(source)
            analysis = analyze_dataset_resync_v2(
                DatasetResyncRequest(config_root, "a_profile")
            )
            self.assertEqual(
                {item.profile_id: item.camera_binding_change_count for item in analysis.profiles},
                {"a_profile": 2, "b_profile": 2},
            )
            result = resynchronize_dataset_v2(
                DatasetResyncRequest(
                    config_root,
                    "a_profile",
                    expected_manifest_sha256=analysis.manifest_sha256,
                    expected_source_inventory_sha256=analysis.source_inventory_sha256,
                )
            )

            self.assertEqual(result.manifest_revision, 2)
            self.assertEqual(_tree_hashes(source), source_before_resync)
            reopened_a = DeviceCentricV2Adapter(config_root, "a_profile")
            reopened_b = DeviceCentricV2Adapter(config_root, "b_profile")
            self.assertEqual(reopened_a.index.frame_ids, ("000000", "000001"))
            self.assertEqual(reopened_b.index.frame_ids, ("000000", "000001"))
            self.assertEqual(
                V2LabelRepository.for_sidecar(reopened_a).load("000000").revision,
                1,
            )
            self.assertEqual(
                V2LabelRepository.for_sidecar(reopened_b).load("000000").revision,
                1,
            )
            self.assertEqual(
                validate_dataset(config_root, profile_id="a_profile").usable_frame_count,
                2,
            )
            self.assertEqual(
                validate_dataset(config_root, profile_id="b_profile").usable_frame_count,
                2,
            )


def _lidar_setup(
    candidate: SensorCandidate,
    sensor_id: str,
    timestamp: TimestampSetup,
) -> LidarSetup:
    return LidarSetup(
        candidate=candidate,
        sensor_id=sensor_id,
        display_name=sensor_id.upper(),
        coordinate_frame=f"lidar:{sensor_id.upper()}",
        point_columns=("x", "y", "z", "intensity"),
        profile_id=f"{sensor_id}_profile",
        profile_display_name=f"{sensor_id.upper()} 라벨링",
        sync_method="timestamp_nearest",
        tolerance_ns=20,
        timestamp=timestamp,
    )


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


def _point(path: Path, x: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<ffff", x, 0.0, 0.0, 1.0))


def _image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 24), color=(20, 40, 60)).save(path, "JPEG")


def _timestamp(path: Path, rows: tuple[tuple[str, int], ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "sample_id,timestamp_ns\n"
        + "".join(f"{sample_id},{value}\n" for sample_id, value in rows),
        encoding="utf-8",
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


if __name__ == "__main__":
    unittest.main()

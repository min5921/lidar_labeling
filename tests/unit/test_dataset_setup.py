from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lidar_label_tool.io.dataset_v2 import load_dataset_manifest_v2
from lidar_label_tool.services.dataset_discovery import discover_dataset
from lidar_label_tool.services.dataset_setup import (
    CameraSetup,
    DatasetSetupError,
    DatasetSetupRequest,
    LidarSetup,
    analyze_generic_dataset,
    create_generic_dataset,
    taxonomy_from_config,
)
from lidar_label_tool.services.dataset_v2_validation import validate_dataset_v2


class DatasetSetupTests(unittest.TestCase):
    def test_analysis_is_read_only_and_source_change_requires_reanalysis(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            config_root = Path(directory) / "config"
            point = source / "AEVA" / "000000.bin"
            _point(point)
            candidate = discover_dataset(source).lidars[0]
            request = DatasetSetupRequest(
                source_root=source,
                config_root=config_root,
                display_name="source",
                dataset_id="ds_setup_analysis",
                lidars=(
                    LidarSetup(
                        candidate=candidate,
                        sensor_id="aeva",
                        display_name="AEVA",
                        coordinate_frame="lidar:AEVA",
                        point_columns=("x", "y", "z", "intensity"),
                        profile_id="aeva_profile",
                        profile_display_name="AEVA",
                        sync_method="lidar_only",
                    ),
                ),
                taxonomy=_taxonomy(),
                coordinate_system_confirmed=True,
            )

            analysis = analyze_generic_dataset(request)

            self.assertEqual(analysis.sync_qa[0][1].lidar_frame_count, 1)
            self.assertFalse(config_root.exists())
            point.write_bytes(b"\x01" * 16)
            with self.assertRaises(DatasetSetupError):
                create_generic_dataset(
                    replace(
                        request,
                        expected_source_inventory_sha256=(
                            analysis.source_inventory_sha256
                        ),
                    )
                )
            self.assertFalse((config_root / "dataset.json").exists())

    def test_rejects_corrupt_representative_pcd_before_creating_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            config_root = Path(directory) / "config"
            _write(source / "AEVA" / "000000.pcd", b"not a PCD payload")
            candidate = discover_dataset(source).lidars[0]
            request = DatasetSetupRequest(
                source_root=source,
                config_root=config_root,
                display_name="source",
                dataset_id="ds_corrupt_pcd",
                lidars=(
                    LidarSetup(
                        candidate=candidate,
                        sensor_id="aeva",
                        display_name="AEVA",
                        coordinate_frame="lidar:AEVA",
                        point_columns=("x", "y", "z", "intensity"),
                        profile_id="aeva_profile",
                        profile_display_name="AEVA",
                        sync_method="lidar_only",
                    ),
                ),
                taxonomy=_taxonomy(),
                coordinate_system_confirmed=True,
            )

            with self.assertRaises(DatasetSetupError):
                create_generic_dataset(request)

            self.assertFalse((config_root / "dataset.json").exists())

    def test_creates_multi_lidar_single_profile_namespaces_without_touching_source(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "한글 원본 데이터"
            _point(source / "lidar" / "AEVA" / "frames" / "000000.bin")
            _point(source / "lidar" / "AEVA" / "frames" / "000001.bin")
            _point(source / "lidar" / "LIDAR_POINTS" / "frames" / "000000.bin")
            _image(source / "camera" / "HEAD" / "images" / "000000.jpg")
            discovery = discover_dataset(source)
            before = _tree_hashes(source)
            lidars = tuple(
                LidarSetup(
                    candidate=candidate,
                    sensor_id=("aeva" if "AEVA" in candidate.directory else "lidar_points"),
                    display_name=candidate.display_name,
                    coordinate_frame=f"lidar:{candidate.display_name}",
                    point_columns=("x", "y", "z", "intensity"),
                    profile_id=(
                        "aeva_profile"
                        if "AEVA" in candidate.directory
                        else "lidar_points_profile"
                    ),
                    profile_display_name=f"{candidate.display_name} 라벨링",
                    sync_method="exact_stem",
                )
                for candidate in discovery.lidars
            )
            camera_candidate = discovery.cameras[0]
            request = DatasetSetupRequest(
                source_root=source,
                config_root=source,
                display_name=source.name,
                dataset_id="ds_setup_fixture",
                lidars=lidars,
                camera=CameraSetup(
                    candidate=camera_candidate,
                    sensor_id="head_camera",
                    display_name="Head camera",
                    coordinate_frame="camera:HEAD",
                ),
                taxonomy=_taxonomy(),
                coordinate_system_confirmed=True,
                default_profile_id="aeva_profile",
            )

            result = create_generic_dataset(request)

            self.assertTrue(result.validation.is_valid, result.validation.issues)
            manifest = load_dataset_manifest_v2(source)
            self.assertEqual(len(manifest.lidars), 2)
            self.assertEqual(len(manifest.profiles), 2)
            self.assertEqual({profile.lidar_id for profile in manifest.profiles}, {"aeva", "lidar_points"})
            self.assertEqual(_tree_hashes(source, exclude_generated=True), before)

    def test_supports_read_only_style_source_with_external_configuration_root(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "원본 with spaces"
            config_root = Path(directory) / "workspace" / "dataset config"
            _point(source / "AEVA" / "000000.bin")
            discovery = discover_dataset(source)
            lidar = LidarSetup(
                candidate=discovery.lidars[0],
                sensor_id="aeva",
                display_name="AEVA",
                coordinate_frame="lidar:AEVA",
                point_columns=("x", "y", "z", "intensity"),
                profile_id="aeva_profile",
                profile_display_name="AEVA labeling",
                sync_method="lidar_only",
            )
            result = create_generic_dataset(
                DatasetSetupRequest(
                    source_root=source,
                    config_root=config_root,
                    display_name=source.name,
                    dataset_id="ds_external_fixture",
                    lidars=(lidar,),
                    taxonomy=_taxonomy(),
                    coordinate_system_confirmed=True,
                )
            )
            self.assertEqual(result.manifest.data_root.kind, "absolute_local")
            self.assertEqual(Path(result.manifest.data_root.path), source.resolve())
            self.assertTrue(validate_dataset_v2(config_root).is_valid)
            self.assertFalse((source / "dataset.json").exists())

    def test_manifest_commit_failure_preserves_source_and_leaves_no_active_generation(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            config_root = Path(directory) / "config"
            _point(source / "AEVA" / "000000.bin")
            candidate = discover_dataset(source).lidars[0]
            request = DatasetSetupRequest(
                source_root=source,
                config_root=config_root,
                display_name="source",
                dataset_id="ds_failure_fixture",
                lidars=(
                    LidarSetup(
                        candidate=candidate,
                        sensor_id="aeva",
                        display_name="AEVA",
                        coordinate_frame="lidar:AEVA",
                        point_columns=("x", "y", "z", "intensity"),
                        profile_id="aeva_profile",
                        profile_display_name="AEVA",
                        sync_method="lidar_only",
                    ),
                ),
                taxonomy=_taxonomy(),
                coordinate_system_confirmed=True,
            )
            before = _tree_hashes(source)
            real_replace = os.replace

            def replace_with_failure(
                src: str | os.PathLike[str],
                dst: str | os.PathLike[str],
            ) -> None:
                if Path(dst).name == "dataset.json":
                    raise OSError("injected manifest replace failure")
                real_replace(src, dst)

            with patch(
                "lidar_label_tool.services.dataset_setup.os.replace",
                side_effect=replace_with_failure,
            ):
                with self.assertRaises(OSError):
                    create_generic_dataset(request)

            self.assertEqual(_tree_hashes(source), before)
            self.assertFalse((config_root / "dataset.json").exists())
            self.assertFalse((config_root / "generations" / "generation-000001").exists())

    def test_post_commit_validation_failure_rolls_back_owned_manifest_and_generation(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            config_root = Path(directory) / "config"
            _point(source / "AEVA" / "000000.bin")
            candidate = discover_dataset(source).lidars[0]
            request = DatasetSetupRequest(
                source_root=source,
                config_root=config_root,
                display_name="source",
                dataset_id="ds_post_commit_failure",
                lidars=(
                    LidarSetup(
                        candidate=candidate,
                        sensor_id="aeva",
                        display_name="AEVA",
                        coordinate_frame="lidar:AEVA",
                        point_columns=("x", "y", "z", "intensity"),
                        profile_id="aeva_profile",
                        profile_display_name="AEVA",
                        sync_method="lidar_only",
                    ),
                ),
                taxonomy=_taxonomy(),
                coordinate_system_confirmed=True,
            )
            before = _tree_hashes(source)

            with patch(
                "lidar_label_tool.services.dataset_setup.validate_dataset_v2",
                side_effect=RuntimeError("injected final validation failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected final validation"):
                    create_generic_dataset(request)

            self.assertEqual(_tree_hashes(source), before)
            self.assertFalse((config_root / "dataset.json").exists())
            self.assertFalse((config_root / "generations" / "generation-000001").exists())


def _taxonomy() -> dict[str, object]:
    return taxonomy_from_config(
        {
            "classes": [
                {
                    "name": "Car",
                    "color": "#00D084",
                    "default_size": [4.2, 1.8, 1.6],
                    "shortcut": "1",
                }
            ],
            "source_class_mappings": {"TYPE_VEHICLE": "Car"},
        }
    )


def _point(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * 16)


def _image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"image")


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _tree_hashes(root: Path, *, exclude_generated: bool = False) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if exclude_generated and (
            relative == "dataset.json" or relative.startswith("generations/")
        ):
            continue
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


if __name__ == "__main__":
    unittest.main()

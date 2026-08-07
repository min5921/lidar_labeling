from __future__ import annotations

import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.dataset_resync_v2 import (
    DatasetResyncCancelled,
    DatasetResyncConflictError,
    DatasetResyncRequest,
    analyze_dataset_resync_v2,
    resynchronize_dataset_v2,
)
from tests.fixture_builders import create_v2_dataset


class DatasetResyncV2Tests(unittest.TestCase):
    def test_cancel_during_fingerprint_keeps_previous_generation_active(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            cancelled = False

            def progress(phase: str, current: int, total: int, message: str) -> None:
                nonlocal cancelled
                del current, total, message
                if phase == "fingerprint":
                    cancelled = True

            with self.assertRaises(DatasetResyncCancelled):
                resynchronize_dataset_v2(
                    DatasetResyncRequest(root, "aeva_profile"),
                    progress=progress,
                    cancel_check=lambda: cancelled,
                )

            self.assertFalse((root / "generations" / "generation-000002").exists())
            self.assertEqual(DeviceCentricV2Adapter(root).manifest.manifest_revision, 1)

    def test_analysis_is_read_only_and_reports_camera_mapping_changes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            (root / "timestamps" / "HEAD_CAMERA.csv").write_text(
                "sample_id,bag_time_ns\n000000,10000\n000001,20000\n",
                encoding="utf-8",
            )

            analysis = analyze_dataset_resync_v2(
                DatasetResyncRequest(root, "aeva_profile")
            )

            self.assertEqual(analysis.current_manifest_revision, 1)
            self.assertEqual(analysis.next_manifest_revision, 2)
            self.assertEqual(analysis.target.camera_binding_change_count, 2)
            self.assertEqual(analysis.target.qa.unmatched_camera_count, 2)
            self.assertFalse((root / "generations" / "generation-000002").exists())

    def test_source_change_after_analysis_is_rejected_before_commit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            analysis = analyze_dataset_resync_v2(
                DatasetResyncRequest(root, "aeva_profile")
            )
            (root / "sensors" / "camera" / "HEAD_CAMERA" / "images" / "000000.jpg").write_bytes(
                b"changed image"
            )

            with self.assertRaises(DatasetResyncConflictError):
                resynchronize_dataset_v2(
                    DatasetResyncRequest(
                        root,
                        "aeva_profile",
                        expected_manifest_sha256=analysis.manifest_sha256,
                        expected_source_inventory_sha256=(
                            analysis.source_inventory_sha256
                        ),
                    )
                )

            self.assertFalse((root / "generations" / "generation-000002").exists())

    def test_resync_creates_new_generation_and_preserves_lidar_labels(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)
            old_adapter = DeviceCentricV2Adapter(root)
            old_repository = V2LabelRepository.for_sidecar(old_adapter)
            label = WaymoLabelImporter({}, "device_centric_v2").import_laser_labels(
                old_adapter.load_source_frame("000000")
            )
            old_repository.save(label)
            camera_csv = root / "timestamps" / "HEAD_CAMERA.csv"
            camera_csv.write_text(
                "sample_id,bag_time_ns\n000000,10000\n000001,20000\n",
                encoding="utf-8",
            )
            source_hash = hashlib.sha256(camera_csv.read_bytes()).hexdigest()

            result = resynchronize_dataset_v2(
                DatasetResyncRequest(root, "aeva_profile")
            )

            self.assertEqual(result.manifest_revision, 2)
            self.assertEqual(result.qa.lidar_frame_count, 2)
            self.assertEqual(result.qa.unmatched_camera_count, 2)
            self.assertTrue((root / "generations" / "generation-000001").is_dir())
            self.assertTrue((root / "generations" / "generation-000002").is_dir())
            self.assertEqual(hashlib.sha256(camera_csv.read_bytes()).hexdigest(), source_hash)
            new_adapter = DeviceCentricV2Adapter(root)
            self.assertEqual(new_adapter.index.frame_ids, ("000000", "000001"))
            self.assertEqual(
                V2LabelRepository.for_sidecar(new_adapter).load("000000").revision,
                1,
            )

    def test_manifest_replace_failure_keeps_previous_generation_active(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            manifest_path = root / "dataset.json"
            before = manifest_path.read_bytes()
            real_replace = os.replace

            def fail_manifest(
                src: str | os.PathLike[str],
                dst: str | os.PathLike[str],
            ) -> None:
                if Path(dst) == manifest_path:
                    raise OSError("injected resync commit failure")
                real_replace(src, dst)

            with patch(
                "lidar_label_tool.services.dataset_resync_v2.os.replace",
                side_effect=fail_manifest,
            ):
                with self.assertRaises(OSError):
                    resynchronize_dataset_v2(
                        DatasetResyncRequest(root, "aeva_profile")
                    )

            self.assertEqual(manifest_path.read_bytes(), before)
            self.assertFalse((root / "generations" / "generation-000002").exists())
            self.assertTrue(DeviceCentricV2Adapter(root).scan().frame_ids)

    def test_post_commit_validation_failure_restores_previous_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            manifest_path = root / "dataset.json"
            before = manifest_path.read_bytes()

            with patch(
                "lidar_label_tool.services.dataset_resync_v2.validate_dataset_v2",
                side_effect=RuntimeError("injected final resync validation failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "injected final resync"):
                    resynchronize_dataset_v2(
                        DatasetResyncRequest(root, "aeva_profile")
                    )

            self.assertEqual(manifest_path.read_bytes(), before)
            self.assertFalse((root / "generations" / "generation-000002").exists())
            self.assertEqual(DeviceCentricV2Adapter(root).manifest.manifest_revision, 1)


if __name__ == "__main__":
    unittest.main()

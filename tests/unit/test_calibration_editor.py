from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

import numpy as np

import lidar_label_tool.calibration_editor.repository as calibration_repository
from lidar_label_tool.calibration.waymo_camera import CameraCalibration
from lidar_label_tool.calibration_editor import (
    CalibrationDraft,
    CalibrationReferenceBoxes,
    CameraIntrinsics,
    PoseDelta,
    build_calibration_document,
    default_adjusted_path,
    load_calibration_file,
    load_calibration_source,
    project_reference_points,
    save_calibration_document,
)
from lidar_label_tool.domain.labels import Box3D
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from tests.fixture_builders import create_v2_dataset


def _generic_camera() -> dict[str, object]:
    return {
        "intrinsic": [[100.0, 0.0, 320.0], [0.0, 100.0, 240.0], [0.0, 0.0, 1.0]],
        "T_camera_reference": np.eye(4, dtype=np.float64).tolist(),
        "correction_delta": PoseDelta(y_m=2.0).matrix().tolist(),
        "image_size": [640, 480],
        "distortion_model": "none",
        "distortion_coefficients": [0.0] * 5,
    }


class CalibrationEditorModelTests(unittest.TestCase):
    def test_existing_correction_is_flattened_into_immutable_baseline(self) -> None:
        draft = CalibrationDraft.from_generic(
            "front",
            "lidar:top",
            _generic_camera(),
            source_path=Path("calibration.json"),
            source_fingerprint="a" * 64,
        )
        self.assertAlmostEqual(draft.base_transform[1, 3], 2.0)
        self.assertTrue(draft.correction.is_identity)

        adjusted = draft.with_correction(PoseDelta(z_m=3.0, yaw_deg=10.0))
        expected = adjusted.correction.matrix() @ draft.base_transform
        np.testing.assert_allclose(adjusted.effective_transform, expected)

    def test_saved_entry_reloads_to_the_same_effective_transform(self) -> None:
        draft = CalibrationDraft.from_generic(
            "front",
            "vehicle",
            _generic_camera(),
            source_path=None,
            source_fingerprint=None,
        ).with_correction(PoseDelta(x_m=0.2, roll_deg=-1.5))
        reloaded = CameraCalibration.from_generic("front", draft.camera_entry())
        np.testing.assert_allclose(
            np.linalg.inv(reloaded.t_vehicle_camera),
            draft.effective_transform,
            atol=1e-10,
        )

    def test_new_draft_uses_explicit_image_based_intrinsic_estimate(self) -> None:
        draft = CalibrationDraft.new("front", "lidar:top", (1280, 720))
        self.assertEqual(draft.intrinsics.fx, 1280.0)
        self.assertEqual(draft.intrinsics.fy, 1280.0)
        self.assertEqual(draft.intrinsics.cx, 639.5)
        self.assertEqual(draft.intrinsics.cy, 359.5)

    def test_point_projection_reports_front_and_image_counts(self) -> None:
        intrinsics = CameraIntrinsics(
            fx=100.0,
            fy=100.0,
            cx=320.0,
            cy=240.0,
            width=640,
            height=480,
        )
        draft = CalibrationDraft(
            camera_id="front",
            reference_frame="vehicle",
            base_transform=np.eye(4, dtype=np.float64),
            base_intrinsics=intrinsics,
            intrinsics=intrinsics,
        )
        projection = project_reference_points(
            np.array(
                [[10.0, 0.0, 0.0], [10.0, -1.0, -2.0], [-1.0, 0.0, 0.0]],
                dtype=np.float32,
            ),
            draft.effective_camera_calibration(),
        )
        self.assertEqual(projection.stats.sampled_points, 3)
        self.assertEqual(projection.stats.points_in_front, 2)
        self.assertEqual(projection.stats.points_in_image, 2)
        np.testing.assert_allclose(projection.uv, [[320.0, 240.0], [330.0, 260.0]])


class CalibrationReferenceBoxesTests(unittest.TestCase):
    def test_boxes_are_frame_scoped_editable_and_fitted_to_point_floor(self) -> None:
        xyz = np.array(
            [
                (9.0 + x_index * 0.5, 1.5 + y_index * 0.5, -0.5)
                for x_index in range(4)
                for y_index in range(4)
            ],
            dtype=np.float32,
        )
        cloud = PointCloudData(
            xyz=xyz,
            attributes={},
            sensor_id="aeva",
            return_id="1",
            source_frame="lidar:AEVA",
            source_path=Path("000000.bin"),
        )
        boxes = CalibrationReferenceBoxes()

        created = boxes.create(
            "000000",
            class_name="Car",
            x=10.0,
            y=2.0,
            length=4.0,
            width=2.0,
            height=2.0,
            clouds=(cloud,),
        )

        self.assertAlmostEqual(created.box3d.z, 0.5)
        self.assertTrue(created.id.startswith("calibration-reference-"))
        self.assertTrue(created.source["temporary"])
        self.assertEqual(boxes.for_frame("000001"), ())

        moved = boxes.replace_box(
            "000000",
            created.id,
            Box3D(
                x=10.0,
                y=2.0,
                z=5.0,
                length=4.0,
                width=2.0,
                height=2.0,
                yaw=0.2,
            ),
        )
        self.assertAlmostEqual(moved.box3d.yaw, 0.2)
        refitted = boxes.fit_to_points("000000", created.id, (cloud,))
        self.assertIsNotNone(refitted)
        assert refitted is not None
        self.assertAlmostEqual(refitted.box3d.z, 0.5)

        self.assertTrue(boxes.delete("000000", created.id))
        self.assertEqual(boxes.for_frame("000000"), ())

    def test_clear_only_removes_the_requested_frame(self) -> None:
        boxes = CalibrationReferenceBoxes()
        for frame_id in ("000000", "000001"):
            boxes.create(
                frame_id,
                class_name="Unknown",
                x=0.0,
                y=0.0,
                length=1.0,
                width=1.0,
                height=1.0,
            )

        self.assertEqual(boxes.clear("000000"), 1)
        self.assertEqual(boxes.for_frame("000000"), ())
        self.assertEqual(len(boxes.for_frame("000001")), 1)


class CalibrationEditorRepositoryTests(unittest.TestCase):
    def test_v2_profile_calibration_is_auto_loaded_and_fingerprint_checked(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = create_v2_dataset(root, with_camera=True)
            calibration = {
                "schema_version": "1.0",
                "reference_frame": "lidar:AEVA",
                "lidars": {
                    "aeva": {"T_reference_sensor": np.eye(4).tolist()}
                },
                "cameras": {"head_camera": _generic_camera()},
            }
            calibration_path = root / "calibration" / "calibration.json"
            calibration_path.parent.mkdir()
            payload = (
                json.dumps(calibration, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            calibration_path.write_bytes(payload)
            profile_camera = manifest["profiles"][0]["camera"]
            profile_camera.update(
                {
                    "mode": "calibrated",
                    "calibration_path": "calibration/calibration.json",
                    "calibration_sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            (root / "dataset.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            adapter = open_dataset_adapter(root, profile_id="aeva_profile")
            index = adapter.scan()
            source = load_calibration_source(adapter, index)
            draft = source.draft_for(
                "head_camera", index.reference_frame, (640, 480)
            )
            self.assertEqual(source.source_kind, "generic")
            self.assertAlmostEqual(draft.base_transform[1, 3], 2.0)

            calibration_path.write_bytes(payload + b"\n")
            with self.assertRaisesRegex(ValueError, "fingerprint"):
                load_calibration_source(adapter, index)

    def test_v2_display_only_dataset_can_save_new_adjusted_calibration(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 calibration dataset"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)
            manifest_before = (root / "dataset.json").read_bytes()
            adapter = open_dataset_adapter(root, profile_id="aeva_profile")
            index = adapter.scan()
            source = load_calibration_source(adapter, index)
            self.assertEqual(source.source_kind, "new")

            draft = source.draft_for(
                "head_camera", index.reference_frame, (640, 480)
            ).with_correction(PoseDelta(x_m=0.1, pitch_deg=0.5))
            document = build_calibration_document(
                source,
                draft,
                adapter,
                index,
                verified_frame_ids=("000000",),
                projection_summary={"points_in_image": 12},
            )
            output = default_adjusted_path(index, "head_camera")
            fingerprint = save_calibration_document(output, document)

            self.assertTrue(output.is_file())
            self.assertEqual(len(fingerprint), 64)
            self.assertEqual((root / "dataset.json").read_bytes(), manifest_before)
            self.assertIn("aeva", document["lidars"])
            self.assertIn("head_camera", document["cameras"])
            metadata = document["metadata"]["calibration_editor"]
            self.assertEqual(metadata["verified_frame_ids"], ["000000"])

            original_output = output.read_bytes()
            changed_document = deepcopy(document)
            changed_document["metadata"]["calibration_editor"]["test"] = "failure"
            real_replace = calibration_repository.os.replace

            def fail_final_replace(source_path: object, target_path: object) -> None:
                if Path(target_path).resolve() == output.resolve():
                    raise OSError("injected final replace failure")
                real_replace(source_path, target_path)

            with mock.patch.object(
                calibration_repository.os,
                "replace",
                side_effect=fail_final_replace,
            ):
                with self.assertRaisesRegex(OSError, "injected final replace failure"):
                    save_calibration_document(output, changed_document)
            self.assertEqual(output.read_bytes(), original_output)

            reloaded_source = load_calibration_file(output)
            reloaded_draft = reloaded_source.draft_for(
                "head_camera", index.reference_frame, (640, 480)
            )
            np.testing.assert_allclose(
                reloaded_draft.effective_transform,
                draft.effective_transform,
                atol=1e-10,
            )
            output.write_text(output.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "changed after it was loaded"):
                save_calibration_document(
                    output.with_name("second.json"),
                    document,
                    source_path=output,
                    expected_source_fingerprint=reloaded_source.source_fingerprint,
                )

    def test_source_path_cannot_be_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "calibration.json"
            source.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cannot be overwritten"):
                save_calibration_document(
                    source,
                    {"not": "validated because path guard follows schema validation"},
                    source_path=source,
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

try:
    import jsonschema
except ImportError:
    jsonschema = None


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "convert_one_chip_dataset.py"
SPEC = importlib.util.spec_from_file_location("convert_one_chip_dataset", SCRIPT)
assert SPEC is not None
converter = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = converter
SPEC.loader.exec_module(converter)

VERIFY_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_one_chip_calibration.py"
VERIFY_SPEC = importlib.util.spec_from_file_location("verify_one_chip_calibration", VERIFY_SCRIPT)
assert VERIFY_SPEC is not None
verifier = importlib.util.module_from_spec(VERIFY_SPEC)
assert VERIFY_SPEC.loader is not None
sys.modules[VERIFY_SPEC.name] = verifier
VERIFY_SPEC.loader.exec_module(verifier)


class OneChipConverterTests(unittest.TestCase):
    def test_calibration_maps_plumb_bob_and_ros_optical_axes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stem in ("cam_left", "cam_right"):
                (root / f"{stem}_intrinsics.yaml").write_text(
                    "\n".join(
                        [
                            f"camera_name: {stem}",
                            "image_width: 2448",
                            "image_height: 2048",
                            "camera_matrix:",
                            "- - 10.0",
                            "  - 0.0",
                            "  - 5.0",
                            "- - 0.0",
                            "  - 11.0",
                            "  - 6.0",
                            "- - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                            "distortion_model: plumb_bob",
                            "distortion_coefficients:",
                            "- 0.1",
                            "- 0.2",
                            "- 0.3",
                            "- 0.4",
                            "- 0.5",
                        ]
                    ),
                    encoding="utf-8",
                )
                (root / f"{stem}_lidar_extrinsics.yaml").write_text(
                    "\n".join(
                        [
                            "transform_lidar_to_camera:",
                            "- - 1.0",
                            "  - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                            "- - 0.0",
                            "  - 1.0",
                            "  - 0.0",
                            "  - 2.0",
                            "- - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                            "  - 3.0",
                            "- - 0.0",
                            "  - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                        ]
                    ),
                    encoding="utf-8",
                )

            calibration = converter.convert_calibration(root)
            left = calibration["cameras"]["CAM_LEFT"]

            self.assertEqual(calibration["reference_frame"], "robosense")
            self.assertEqual(left["distortion_model"], "brown_conrady")
            self.assertEqual(left["image_size"], [2448, 2048])
            np.testing.assert_allclose(
                left["T_camera_reference"],
                converter.OPTICAL_TO_TOOL_CAMERA
                @ np.array(
                    [
                        [1.0, 0.0, 0.0, 1.0],
                        [0.0, 1.0, 0.0, 2.0],
                        [0.0, 0.0, 1.0, 3.0],
                        [0.0, 0.0, 0.0, 1.0],
                    ]
                ),
            )

    def test_calibration_verifier_accepts_regenerated_yaml_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for stem in ("cam_left", "cam_right"):
                (root / f"{stem}_intrinsics.yaml").write_text(
                    "\n".join(
                        [
                            f"camera_name: {stem}",
                            "image_width: 2448",
                            "image_height: 2048",
                            "camera_matrix:",
                            "- - 10.0",
                            "  - 0.0",
                            "  - 5.0",
                            "- - 0.0",
                            "  - 11.0",
                            "  - 6.0",
                            "- - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                            "distortion_model: plumb_bob",
                            "distortion_coefficients:",
                            "- 0.1",
                            "- 0.2",
                            "- 0.3",
                            "- 0.4",
                            "- 0.5",
                        ]
                    ),
                    encoding="utf-8",
                )
                (root / f"{stem}_lidar_extrinsics.yaml").write_text(
                    "\n".join(
                        [
                            "transform_lidar_to_camera:",
                            "- - 1.0",
                            "  - 0.0",
                            "  - 0.0",
                            "  - 0.0",
                            "- - 0.0",
                            "  - 1.0",
                            "  - 0.0",
                            "  - 0.0",
                            "- - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                            "  - 0.0",
                            "- - 0.0",
                            "  - 0.0",
                            "  - 0.0",
                            "  - 1.0",
                        ]
                    ),
                    encoding="utf-8",
                )

            current = converter.convert_calibration(root)
            regenerated = converter.convert_calibration(root)
            basic_issues = verifier._validate_basic_calibration(current)
            comparison, comparison_issues = verifier._compare_to_regenerated(
                current,
                regenerated,
            )

            self.assertEqual([], [issue for issue in basic_issues if issue.level == "error"])
            self.assertEqual([], comparison_issues)
            self.assertTrue(comparison["reference_frame_match"])
            self.assertEqual(
                comparison["cameras"]["CAM_LEFT"]["transform_max_abs_diff"],
                0.0,
            )
            self.assertEqual(
                comparison["cameras"]["CAM_LEFT"]["distortion_model"],
                "brown_conrady",
            )

    def test_nearest_sample_respects_tolerance(self) -> None:
        samples = [
            converter.TimedSample("a", 1_000, "bag", 0),
            converter.TimedSample("b", 2_000, "bag", 1),
        ]

        sample, delta = converter.nearest_sample(1_700, samples, 500)
        self.assertEqual(sample.sample_id, "b")
        self.assertEqual(delta, 300)

        sample, delta = converter.nearest_sample(3_000, samples, 500)
        self.assertIsNone(sample)
        self.assertEqual(delta, -1_000)

    def test_one_chip_manifest_defaults_to_simple_physical_paths(self) -> None:
        layout = converter.dataset_layout_paths("simple")
        manifest = converter._manifest("dataset", "robosense", layout)
        sensors = {sensor["id"]: sensor for sensor in manifest["sensors"]}

        self.assertEqual(manifest["storage_layout"], "simple")
        self.assertEqual(
            sensors["MERGED"]["data_patterns"]["return1"],
            "lidar/{sample_id}.bin",
        )
        self.assertEqual(
            sensors["CAM_LEFT"]["data_patterns"]["image"],
            "cam_left/{sample_id}.jpg",
        )
        self.assertEqual(
            sensors["CAM_RIGHT"]["data_patterns"]["image"],
            "cam_right/{sample_id}.jpg",
        )

    @unittest.skipIf(jsonschema is None, "jsonschema optional dependency is not installed")
    def test_one_chip_manifest_matches_dataset_schema(self) -> None:
        schema_path = Path(__file__).resolve().parents[2] / "schemas" / "dataset.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        for layout_name in ("simple", "legacy"):
            manifest = converter._manifest(
                "dataset", "robosense", converter.dataset_layout_paths(layout_name)
            )
            jsonschema.validate(manifest, schema)

    def test_one_chip_legacy_layout_remains_available(self) -> None:
        layout = converter.dataset_layout_paths("legacy")
        manifest = converter._manifest("dataset", "robosense", layout)
        sensors = {sensor["id"]: sensor for sensor in manifest["sensors"]}

        self.assertEqual(manifest["storage_layout"], "legacy")
        self.assertEqual(
            sensors["MERGED"]["data_patterns"]["return1"],
            "sensors/lidar/MERGED/frames/{sample_id}.bin",
        )

    def test_header_aligned_timestamp_preserves_header_interval_on_log_clock(self) -> None:
        message = converter.McapMessage(
            topic="/topic",
            sequence=0,
            log_time_ns=1_000_000,
            publish_time_ns=1_000_000,
            data=b"",
        )
        header = converter.DecodedHeader(stamp_ns=250_000, frame_id="sensor")

        timestamp = converter._timestamp_for(
            message,
            header,
            "header_aligned",
            header_log_offset_ns=750_000,
        )

        self.assertEqual(timestamp, 1_000_000)

    def test_sync_report_flags_repeated_camera_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "frames.jsonl"
            lidar = [
                converter.TimedSample("000000", 0, "bag", 0),
                converter.TimedSample("000001", 100_000_000, "bag", 1),
                converter.TimedSample("000002", 200_000_000, "bag", 2),
                converter.TimedSample("000003", 300_000_000, "bag", 3),
            ]
            camera = [
                converter.TimedSample("000010", 0, "bag", 0),
                converter.TimedSample("000012", 300_000_000, "bag", 1),
            ]

            report = converter.write_frames_jsonl(
                target,
                lidar,
                {"CAM_LEFT": camera},
                tolerance_ns=250_000_000,
            )

            qa = report["camera_sequence_qa"]["CAM_LEFT"]
            self.assertEqual(qa["max_repeat_run_frames"], 2)
            self.assertEqual(qa["repeated_frame_count"], 2)
            self.assertEqual(qa["repeat_runs_first20"][0]["sample_id"], "000010")
            self.assertEqual(qa["jump_examples_first20"][0]["step"], 2)


if __name__ == "__main__":
    unittest.main()

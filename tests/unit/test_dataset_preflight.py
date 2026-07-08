from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.services.dataset_preflight import (
    probe_writable_directory,
    validate_dataset,
)
from tests.fixture_builders import (
    CLASS_MAPPING,
    create_device_dataset,
    source_object,
    write_source_labels,
)


class DatasetPreflightTests(unittest.TestCase):
    def test_probe_writable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "annotations"
            writable, error = probe_writable_directory(target)
            self.assertTrue(writable)
            self.assertIsNone(error)
            self.assertFalse(target.exists())

    def test_probe_reports_invalid_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("blocked", encoding="utf-8")
            writable, error = probe_writable_directory(blocker / "annotations")
            self.assertFalse(writable)
            self.assertIn("Error", error or "")

    def test_valid_fixture_returns_structured_report_without_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)

            report = validate_dataset(root, class_mapping=CLASS_MAPPING)

            self.assertEqual(report.dataset_id, "preflight_fixture")
            self.assertEqual(report.frame_count, 1)
            self.assertEqual(report.usable_frame_count, 1)
            self.assertEqual(report.exit_code, 0)
            self.assertEqual(report.lidar_availability[0].available_frames, 1)
            self.assertEqual(report.to_dict()["issue_counts"]["error"], 0)

    def test_missing_point_cloud_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root, frame_count=2)
            (root / "sensors" / "lidar" / "MERGED" / "000001.bin").unlink()

            report = validate_dataset(root, class_mapping=CLASS_MAPPING)

            self.assertEqual(report.exit_code, 2)
            issue = next(issue for issue in report.issues if issue.code == "missing_point_cloud")
            self.assertEqual(issue.frame_id, "000001")
            self.assertEqual(issue.sensor_id, "MERGED")

    def test_malformed_source_label_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            labels = root / "source_labels" / "laser"
            labels.mkdir(parents=True)
            (labels / "000000.json").write_text("{not-json", encoding="utf-8")

            report = validate_dataset(root, class_mapping=CLASS_MAPPING)

            self.assertEqual(report.exit_code, 2)
            self.assertTrue(
                any(issue.code == "malformed_source_label" for issue in report.issues)
            )

    def test_invalid_bin_stride_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            (root / "sensors" / "lidar" / "MERGED" / "000000.bin").write_bytes(b"bad")

            report = validate_dataset(root, class_mapping=CLASS_MAPPING)

            self.assertEqual(report.exit_code, 2)
            self.assertTrue(any(issue.code == "invalid_bin_stride" for issue in report.issues))

    def test_unknown_source_class_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            write_source_labels(root, "000000", [source_object("alien-1", "TYPE_ALIEN")])

            report = validate_dataset(root, class_mapping=CLASS_MAPPING)

            self.assertEqual(report.exit_code, 1)
            self.assertEqual(dict(report.source_class_counts), {"Unknown": 1})
            self.assertTrue(
                any(issue.code == "unknown_source_class" for issue in report.issues)
            )


if __name__ == "__main__":
    unittest.main()

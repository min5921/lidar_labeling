from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any, cast
import unittest

from lidar_label_tool.io.dataset_v2 import (
    canonical_frame_index_bytes,
    load_dataset_manifest_v2,
    load_frame_index_v2,
    load_taxonomy_v2,
    read_dataset_manifest_header,
)
from lidar_label_tool.io.json_schema import JsonSchemaValidationError
from lidar_label_tool.services.dataset_v2_validation import validate_dataset_v2
from tests.fixture_builders import create_v2_dataset


class DatasetV2FoundationTests(unittest.TestCase):
    def test_reader_builds_immutable_domain_models(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터 세트 01"
            root.mkdir()
            create_v2_dataset(root)

            header = read_dataset_manifest_header(root)
            manifest = load_dataset_manifest_v2(root)
            profile = manifest.profile("aeva_profile")
            self.assertEqual(header.schema_version, "2.0")
            self.assertEqual(header.layout, "device_centric_v2")
            self.assertEqual(manifest.dataset_id, "ds_fixture_v2")
            self.assertEqual(manifest.lidar("aeva").point_spec.columns, (  # type: ignore[union-attr]
                "x",
                "y",
                "z",
                "intensity",
            ))
            self.assertIsNotNone(profile)
            assert profile is not None

            index_path = root / profile.frame_index.path
            records = load_frame_index_v2(index_path)
            taxonomy = load_taxonomy_v2(root / manifest.taxonomy.path)
            self.assertEqual(tuple(record.frame_id for record in records), ("000000", "000001"))
            self.assertEqual(canonical_frame_index_bytes(records), index_path.read_bytes())
            self.assertEqual(taxonomy.classes[0].id, "car")

    def test_reader_rejects_v2_schema_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = create_v2_dataset(root)
            manifest["lidars"][0]["id"] = "AEVA"  # type: ignore[index]
            _write_manifest(root, manifest)

            with self.assertRaises(JsonSchemaValidationError) as raised:
                load_dataset_manifest_v2(root)
            self.assertTrue(
                any(
                    violation.pointer == "/lidars/0/id"
                    for violation in raised.exception.violations
                )
            )

    def test_semantic_validator_accepts_valid_lidar_only_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "한글 경로"
            root.mkdir()
            create_v2_dataset(root, frame_count=3)

            report = validate_dataset_v2(root)

            self.assertTrue(report.is_valid, report.issues)
            self.assertEqual(report.error_count, 0)
            self.assertEqual(report.warning_count, 0)
            self.assertEqual(report.data_root, root.resolve())
            self.assertEqual(len(report.frame_indexes[0].records), 3)

    def test_semantic_validator_checks_timestamp_clock_and_delta(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            valid_root = Path(directory) / "valid"
            valid_root.mkdir()
            create_v2_dataset(valid_root, with_camera=True)
            self.assertTrue(validate_dataset_v2(valid_root).is_valid)

            mismatch_root = Path(directory) / "clock-mismatch"
            mismatch_root.mkdir()
            create_v2_dataset(
                mismatch_root,
                with_camera=True,
                camera_clock_domain="device",
            )
            mismatch = validate_dataset_v2(mismatch_root)
            self.assertIn(
                "clock_domain_mismatch",
                {issue.code for issue in mismatch.issues},
            )

            manifest = json.loads((valid_root / "dataset.json").read_text(encoding="utf-8"))
            records = _read_index_records(valid_root, manifest)
            records[0]["camera"]["delta_ns"] = 11  # type: ignore[index]
            _rewrite_index_and_manifest(valid_root, manifest, records)
            invalid_delta = validate_dataset_v2(valid_root)
            self.assertIn(
                "timestamp_delta_invalid",
                {issue.code for issue in invalid_delta.issues},
            )

    def test_missing_camera_image_is_warning_and_keeps_lidar_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            (root / "sensors" / "camera" / "HEAD_CAMERA" / "images" / "000000.jpg").unlink()

            report = validate_dataset_v2(root)

            self.assertTrue(report.is_valid)
            self.assertIn("camera_file_missing", {issue.code for issue in report.issues})

    def test_semantic_validator_rejects_changed_lidar_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = create_v2_dataset(root)
            records = _read_index_records(root, manifest)
            records[0]["frame_id"] = "changed"
            _rewrite_index_and_manifest(root, manifest, records)

            report = validate_dataset_v2(root)
            codes = {issue.code for issue in report.issues}

            self.assertFalse(report.is_valid)
            self.assertIn("frame_binding_mismatch", codes)

    def test_semantic_validator_reports_missing_and_invalid_lidar_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            (root / "sensors" / "lidar" / "AEVA" / "frames" / "000000.bin").unlink()
            invalid = root / "sensors" / "lidar" / "AEVA" / "frames" / "000001.bin"
            invalid.write_bytes(b"bad")

            report = validate_dataset_v2(root)
            codes = {issue.code for issue in report.issues}

            self.assertIn("lidar_file_missing", codes)
            self.assertIn("lidar_stride_invalid", codes)

    def test_semantic_validator_rejects_duplicate_profile_and_noncanonical_index(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = create_v2_dataset(root)
            profiles = cast(list[dict[str, Any]], manifest["profiles"])
            profiles.append(deepcopy(profiles[0]))
            records = _read_index_records(root, manifest)
            _rewrite_index_and_manifest(root, manifest, records, canonical=False)

            report = validate_dataset_v2(root)
            codes = {issue.code for issue in report.issues}

            self.assertIn("profile_id_duplicate", codes)
            self.assertIn("frame_index_not_canonical", codes)


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    (root / "dataset.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _index_path(root: Path, manifest: dict[str, object]) -> Path:
    profiles = manifest["profiles"]
    assert isinstance(profiles, list)
    frame_index = profiles[0]["frame_index"]
    return root / frame_index["path"]


def _read_index_records(
    root: Path,
    manifest: dict[str, object],
) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in _index_path(root, manifest).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rewrite_index_and_manifest(
    root: Path,
    manifest: dict[str, object],
    records: list[dict[str, object]],
    *,
    canonical: bool = True,
) -> None:
    if canonical:
        payload = "".join(
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
            for record in records
        ).encode("utf-8")
    else:
        payload = (json.dumps(records[0], ensure_ascii=False) + "\n").encode("utf-8")
    index_path = _index_path(root, manifest)
    index_path.write_bytes(payload)
    profiles = manifest["profiles"]
    assert isinstance(profiles, list)
    frame_index = profiles[0]["frame_index"]
    frame_index["sha256"] = hashlib.sha256(payload).hexdigest()
    _write_manifest(root, manifest)


if __name__ == "__main__":
    unittest.main()

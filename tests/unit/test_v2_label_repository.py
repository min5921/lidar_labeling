from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.json_repository import LabelConflictError
from lidar_label_tool.io.labels.v2_repository import (
    V2LabelIdentityError,
    V2LabelRepository,
)
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from tests.fixture_builders import create_v2_dataset


class V2LabelRepositoryTests(unittest.TestCase):
    def test_same_revision_external_edit_is_not_overwritten_until_reload(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            repository.save(_new_label(adapter))
            stale = repository.load("000000")
            target = repository.path_for("000000")
            document = json.loads(target.read_text(encoding="utf-8"))
            document["external_note"] = "외부 작업 보존"
            target.write_text(json.dumps(document), encoding="utf-8")
            changed_bytes = target.read_bytes()

            for _ in range(2):
                with self.assertRaises(LabelConflictError):
                    repository.save(stale)
                self.assertEqual(target.read_bytes(), changed_bytes)
                self.assertFalse(target.with_suffix(".json.bak").exists())

            current = repository.load("000000")
            saved = repository.save(current)
            self.assertEqual(saved.revision, 2)
            self.assertEqual(saved.extra_fields["external_note"], "외부 작업 보존")
            self.assertEqual(target.with_suffix(".json.bak").read_bytes(), changed_bytes)

    def test_successful_save_establishes_next_save_fingerprint(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            saved = repository.save(_new_label(adapter))
            target = repository.path_for("000000")
            document = json.loads(target.read_text(encoding="utf-8"))
            document["external_note"] = "keep"
            target.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(LabelConflictError):
                repository.save(saved)

    def test_saves_and_loads_profile_scoped_v2_label(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            label = _new_label(adapter)
            label = replace(
                label,
                objects=(
                    LabeledObject(
                        id="car-1",
                        class_name="car",
                        box3d=Box3D(1.0, 2.0, 0.5, 4.2, 1.8, 1.6, 0.1),
                        extra_fields={"vendor_field": 7},
                    ),
                ),
                extra_fields={"review_note": "확인"},
            )

            saved = repository.save(label)
            loaded = repository.load("000000")
            document = json.loads(repository.path_for("000000").read_text(encoding="utf-8"))

            self.assertEqual(saved.revision, 1)
            self.assertEqual(loaded.objects[0].class_name, "car")
            self.assertEqual(loaded.objects[0].extra_fields["vendor_field"], 7)
            self.assertEqual(document["schema_version"], "2.0")
            self.assertEqual(document["profile_id"], "aeva_profile")
            self.assertEqual(document["label_lidar_id"], "aeva")
            self.assertEqual(document["objects"][0]["class_id"], "car")
            self.assertEqual(
                repository.path_for("000000").parent,
                (root / "annotations" / "lidar_label_tool" / "aeva_profile" / "aeva").resolve(),
            )

    def test_missing_camera_file_does_not_block_lidar_label_save(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root, with_camera=True)
            (root / "sensors" / "camera" / "HEAD_CAMERA" / "images" / "000000.jpg").unlink()
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)

            repository.save(_new_label(adapter))
            document = json.loads(repository.path_for("000000").read_text(encoding="utf-8"))

            self.assertIsNone(document["image_path"])
            self.assertIsNone(document["provenance"]["image_sha256"])

    def test_identity_point_binding_and_taxonomy_are_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            label = _new_label(adapter)

            with self.assertRaises(V2LabelIdentityError):
                repository.save(replace(label, reference_frame="other"))
            with self.assertRaises(V2LabelIdentityError):
                repository.save(
                    replace(label, point_cloud_paths={"aeva": ("wrong.bin",)})
                )
            unknown = replace(
                label,
                objects=(
                    LabeledObject(
                        "object",
                        "unknown_class",
                        Box3D(0, 0, 0, 1, 1, 1, 0),
                    ),
                ),
            )
            with self.assertRaises(V2LabelIdentityError):
                repository.save(unknown)

    def test_changed_point_bytes_reject_existing_label(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            repository.save(_new_label(adapter))
            point = root / "sensors" / "lidar" / "AEVA" / "frames" / "000000.bin"
            point.write_bytes(b"\x01" * 16)

            with self.assertRaises(V2LabelIdentityError):
                repository.load("000000")

    def test_revision_and_replace_failure_preserve_existing_label(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            saved = repository.save(_new_label(adapter))
            target = repository.path_for("000000")
            before = target.read_bytes()
            real_replace = os.replace

            def fail_target_replace(
                src: str | os.PathLike[str],
                dst: str | os.PathLike[str],
            ) -> None:
                if Path(dst) == target:
                    raise OSError("injected replace failure")
                real_replace(src, dst)

            with patch(
                "lidar_label_tool.io.labels.v2_repository.os.replace",
                side_effect=fail_target_replace,
            ):
                with self.assertRaises(OSError):
                    repository.save(saved)
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(repository.load("000000").revision, 1)

            with self.assertRaises(LabelConflictError):
                repository.save(replace(saved, revision=0))


def _new_label(adapter: DeviceCentricV2Adapter):
    return WaymoLabelImporter({}, source_format="device_centric_v2").import_laser_labels(
        adapter.load_source_frame("000000")
    )


if __name__ == "__main__":
    unittest.main()

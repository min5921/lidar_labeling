from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.recovery_v2 import V2RecoveryStore
from tests.fixture_builders import create_v2_dataset


class V2RecoveryTests(unittest.TestCase):
    def test_recovery_round_trip_preserves_profile_identity_and_base_revision(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            base = repository.save(_new_label(adapter))
            store = V2RecoveryStore(repository)
            dirty = replace(base, frame_status="in_progress")

            written = store.write(
                dirty,
                base_revision=base.revision,
                working_label_path=repository.path_for("000000"),
                tool_version="test",
            )
            loaded = store.load("000000")
            document = json.loads(store.path_for("000000").read_text(encoding="utf-8"))

            self.assertEqual(written.profile_id, "aeva_profile")
            self.assertEqual(written.label_lidar_id, "aeva")
            self.assertEqual(loaded.base_revision, 1)
            self.assertEqual(loaded.label.revision, 1)
            self.assertEqual(document["schema_version"], "2.0")
            self.assertEqual(document["label"]["schema_version"], "2.0")

    def test_recovery_rejects_other_profile_identity_and_changed_base(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            adapter = DeviceCentricV2Adapter(root)
            repository = V2LabelRepository.for_sidecar(adapter)
            base = repository.save(_new_label(adapter))
            store = V2RecoveryStore(repository)
            store.write(
                base,
                base_revision=1,
                working_label_path=repository.path_for("000000"),
                tool_version="test",
            )
            path = store.path_for("000000")
            document = json.loads(path.read_text(encoding="utf-8"))
            document["profile_id"] = "other_profile"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertIsNotNone(store.inspect("000000").error)

            path.unlink()
            store.write(
                base,
                base_revision=1,
                working_label_path=repository.path_for("000000"),
                tool_version="test",
            )
            repository.save(base)
            self.assertIsNotNone(store.inspect("000000").error)


def _new_label(adapter: DeviceCentricV2Adapter):
    return WaymoLabelImporter({}, source_format="device_centric_v2").import_laser_labels(
        adapter.load_source_frame("000000")
    )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.services.annotation_history import AnnotationHistory
from lidar_label_tool.services.recovery import RecoveryStore
from lidar_label_tool.ui.main_window import MainWindow


def _label() -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset-a",
        frame_id="000001",
        point_cloud_paths={"MERGED": ("points/000001.bin",)},
        image_paths={},
        reference_frame="vehicle",
        revision=3,
        objects=(LabeledObject("id-1", "Car", Box3D(1, 2, 0.5, 4, 2, 1.5, 0.2)),),
    )


class _StatusMessage:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:
        self.text = text


class _SaveHarness:
    def __init__(self, repository: LabelRepository, recovery_store: RecoveryStore) -> None:
        baseline = replace(_label(), revision=0)
        self.history = AnnotationHistory.start(baseline)
        self.history.apply(replace(baseline, frame_status="in_progress"))
        self.payload = None
        self.repository = repository
        self.recovery_store = recovery_store
        self.status_message = _StatusMessage()
        self.edit_state_updated = False

    def _update_edit_state(self) -> None:
        self.edit_state_updated = True


class RecoveryStoreTests(unittest.TestCase):
    def test_write_and_load_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            store = RecoveryStore(Path(directory))
            label = replace(_label(), frame_status="in_progress")

            written = store.write(
                label,
                base_revision=3,
                working_label_path=Path(directory) / "000001.json",
                tool_version="test",
            )
            loaded = store.load("000001")

            self.assertEqual(loaded, written)
            self.assertEqual(loaded.label, FrameLabel.from_dict(label.to_dict()))
            self.assertIn(".recovery", str(store.path_for("000001")))

    def test_detects_recovery_newer_than_working_label(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecoveryStore(root)
            working = root / "000001.json"
            working.write_text("{}", encoding="utf-8")
            store.write(
                _label(),
                base_revision=3,
                working_label_path=working,
                tool_version="test",
            )
            recovery = store.path_for("000001")
            os.utime(working, ns=(1_000_000_000, 1_000_000_000))
            os.utime(recovery, ns=(2_000_000_000, 2_000_000_000))

            self.assertTrue(store.is_newer_than_working("000001", working))
            os.utime(working, ns=(3_000_000_000, 3_000_000_000))
            self.assertFalse(store.is_newer_than_working("000001", working))

    def test_delete_after_save_is_idempotent(self) -> None:
        with TemporaryDirectory() as directory:
            store = RecoveryStore(Path(directory))
            store.write(
                _label(), base_revision=3, working_label_path=None, tool_version="test"
            )

            self.assertTrue(store.delete("000001"))
            self.assertFalse(store.delete("000001"))

    def test_normal_main_window_save_removes_recovery_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            repository = LabelRepository(Path(directory), "dataset-a")
            store = RecoveryStore(repository.annotation_dir)
            harness = _SaveHarness(repository, store)
            store.write(
                harness.history.current,
                base_revision=0,
                working_label_path=repository.path_for("000001"),
                tool_version="test",
            )

            saved = MainWindow._save_working_label(harness)

            self.assertTrue(saved)
            self.assertFalse(store.path_for("000001").exists())
            self.assertEqual(repository.load("000001").revision, 1)
            self.assertTrue(harness.edit_state_updated)

    def test_invalid_json_is_reported_without_raising_from_inspect(self) -> None:
        with TemporaryDirectory() as directory:
            store = RecoveryStore(Path(directory))
            path = store.path_for("000001")
            path.parent.mkdir(parents=True)
            path.write_text("{not-json", encoding="utf-8")

            result = store.inspect("000001")

            self.assertIsNone(result.snapshot)
            self.assertIsNotNone(result.error)


if __name__ == "__main__":
    unittest.main()

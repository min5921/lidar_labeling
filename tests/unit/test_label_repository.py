from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.labels.json_repository import LabelConflictError, LabelRepository


def _label(revision: int = 0) -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset-a",
        frame_id="frame_000",
        point_cloud_paths={"TOP": ("points.bin",)},
        image_paths={},
        reference_frame="vehicle",
        revision=revision,
        objects=(LabeledObject("id-1", "Car", Box3D(0, 0, 0, 4, 2, 2, 0)),),
    )


class LabelRepositoryTests(unittest.TestCase):
    def test_atomic_save_revision_backup_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = LabelRepository.for_workspace(Path(directory), "dataset-a")
            first = repository.save(_label())
            self.assertEqual(first.revision, 1)
            second = repository.save(replace(first, frame_status="in_progress"))
            self.assertEqual(second.revision, 2)
            self.assertEqual(repository.load("frame_000").frame_status, "in_progress")
            self.assertEqual(repository.load_backup("frame_000").revision, 1)
            with self.assertRaises(LabelConflictError):
                repository.save(first)

    def test_rejects_unsafe_frame_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = LabelRepository.for_workspace(Path(directory), "dataset-a")
            with self.assertRaises(ValueError):
                repository.path_for("../frame")

    def test_rejects_unsafe_dataset_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                LabelRepository.for_workspace(Path(directory), "../dataset")


if __name__ == "__main__":
    unittest.main()

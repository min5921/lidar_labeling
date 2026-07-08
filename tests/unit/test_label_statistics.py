from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.services.label_statistics import collect_label_statistics
from lidar_label_tool.services.recovery import RecoveryStore
from tests.fixture_builders import (
    CLASS_MAPPING,
    create_device_dataset,
    source_object,
    write_source_labels,
)


class LabelStatisticsTests(unittest.TestCase):
    def test_source_statistics(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root, frame_count=2)
            write_source_labels(root, "000000", [source_object("car-1")])
            write_source_labels(
                root,
                "000001",
                [
                    source_object("ped-1", "TYPE_PEDESTRIAN"),
                    source_object("ped-2", "TYPE_PEDESTRIAN"),
                ],
            )

            statistics = collect_label_statistics(root, class_mapping=CLASS_MAPPING)

            self.assertEqual(statistics.mode, "source")
            self.assertEqual(statistics.object_count, 3)
            self.assertEqual(dict(statistics.class_counts), {"Car": 1, "Pedestrian": 2})
            self.assertEqual(statistics.average_objects_per_frame, 1.5)
            self.assertEqual(statistics.min_objects_per_frame, 1)
            self.assertEqual(statistics.max_objects_per_frame, 2)
            self.assertEqual(statistics.source_label_count, 2)

    def test_working_statistics_and_recovery_count(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root, frame_count=2)
            repository = LabelRepository.for_sidecar(root, "preflight_fixture")
            label = FrameLabel(
                dataset_id="preflight_fixture",
                frame_id="000000",
                point_cloud_paths={"MERGED": ("sensors/lidar/MERGED/000000.bin",)},
                image_paths={},
                reference_frame="vehicle",
                frame_status="in_progress",
                objects=(
                    LabeledObject("working-1", "Car", Box3D(1, 2, 0.5, 4, 2, 1.5, 0)),
                ),
            )
            saved = repository.save(label)
            RecoveryStore(repository.annotation_dir).write(
                saved,
                base_revision=saved.revision,
                working_label_path=repository.path_for(saved.frame_id),
                tool_version="test",
            )

            statistics = collect_label_statistics(
                root, class_mapping=CLASS_MAPPING, working=True
            )

            self.assertEqual(statistics.mode, "working")
            self.assertEqual(statistics.working_label_count, 1)
            self.assertEqual(statistics.object_count, 1)
            self.assertEqual(dict(statistics.status_counts)["in_progress"], 1)
            self.assertEqual(dict(statistics.status_counts)["unvisited"], 1)
            self.assertEqual(statistics.min_objects_per_frame, 0)
            self.assertEqual(statistics.recovery_snapshot_count, 1)


if __name__ == "__main__":
    unittest.main()

import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.services.box_propagation import created_objects, merge_carried_objects


def _object(object_id: str, *, created: bool) -> LabeledObject:
    return LabeledObject(
        id=object_id,
        class_name="Car",
        box3d=Box3D(1, 2, 1, 4, 2, 2, 0),
        source={"created_by": "lidar_label_tool"} if created else {"source_id": object_id},
    )


def _label(*objects: LabeledObject) -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset",
        frame_id="000001",
        point_cloud_paths={"MERGED": ("000001.bin",)},
        image_paths={},
        reference_frame="vehicle",
        objects=objects,
    )


class BoxPropagationTests(unittest.TestCase):
    def test_created_objects_excludes_imported_source_labels(self) -> None:
        manual = _object("manual", created=True)
        imported = _object("source", created=False)
        self.assertEqual(created_objects((imported, manual)), (manual,))

    def test_merge_carried_objects_preserves_target_and_skips_duplicate_ids(self) -> None:
        existing = _object("existing", created=False)
        duplicate = _object("existing", created=True)
        new = _object("new", created=True)

        merged, added_ids = merge_carried_objects(_label(existing), (duplicate, new))

        self.assertEqual(merged.objects, (existing, new))
        self.assertEqual(merged.frame_status, "in_progress")
        self.assertEqual(added_ids, ("new",))


if __name__ == "__main__":
    unittest.main()

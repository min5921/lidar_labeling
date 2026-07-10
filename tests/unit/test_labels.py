import math
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject


class LabelModelTests(unittest.TestCase):
    def test_box_normalizes_yaw(self) -> None:
        box = Box3D(1, 2, 3, 4, 2, 1, 3 * math.pi)
        self.assertAlmostEqual(box.yaw, -math.pi)

    def test_box_rejects_non_positive_dimensions(self) -> None:
        with self.assertRaises(ValueError):
            Box3D(0, 0, 0, 0, 1, 1, 0)

    def test_frame_round_trip_preserves_string_ids(self) -> None:
        label = FrameLabel(
            dataset_id="dataset",
            frame_id="frame_000",
            point_cloud_paths={"TOP": ("top_r1.bin", "top_r2.bin")},
            image_paths={"FRONT": "front.jpg"},
            reference_frame="vehicle",
            objects=(
                LabeledObject(
                    id="source-string-id",
                    class_name="Car",
                    box3d=Box3D(1, 2, 0.5, 4.2, 1.8, 1.6, 0.1),
                    attributes={"difficulty": "normal"},
                ),
            ),
        )
        restored = FrameLabel.from_dict(label.to_dict())
        self.assertEqual(restored.objects[0].id, "source-string-id")
        self.assertEqual(restored.point_cloud_paths["TOP"], ("top_r1.bin", "top_r2.bin"))

    def test_round_trip_preserves_unknown_frame_and_object_fields(self) -> None:
        data = FrameLabel(
            dataset_id="dataset",
            frame_id="frame_000",
            point_cloud_paths={"TOP": ("top.bin",)},
            image_paths={},
            reference_frame="vehicle",
            objects=(
                LabeledObject(
                    id="source-id",
                    class_name="Car",
                    box3d=Box3D(1, 2, 3, 4, 2, 1, 0),
                ),
            ),
        ).to_dict()
        data["future_frame_field"] = {"keep": True}
        data["objects"][0]["future_object_field"] = [1, 2, 3]

        restored = FrameLabel.from_dict(data).to_dict()

        self.assertEqual(restored["future_frame_field"], {"keep": True})
        self.assertEqual(restored["objects"][0]["future_object_field"], [1, 2, 3])

    def test_frame_rejects_duplicate_ids(self) -> None:
        obj = LabeledObject("same", "Car", Box3D(0, 0, 0, 1, 1, 1, 0))
        with self.assertRaises(ValueError):
            FrameLabel(
                dataset_id="dataset",
                frame_id="frame",
                point_cloud_paths={"TOP": ("points.bin",)},
                image_paths={},
                reference_frame="vehicle",
                objects=(obj, obj),
            )

    def test_reads_legacy_single_sensor_paths(self) -> None:
        data = FrameLabel(
            dataset_id="dataset",
            frame_id="frame",
            point_cloud_paths={"TOP": ("top.bin",)},
            image_paths={"FRONT": "front.jpg"},
            reference_frame="vehicle",
        ).to_dict()
        data.pop("point_cloud_paths")
        data.pop("image_paths")
        data["point_cloud_path"] = "legacy.bin"
        data["image_path"] = "legacy.jpg"
        restored = FrameLabel.from_dict(data)
        self.assertEqual(restored.point_cloud_paths, {"PRIMARY": ("legacy.bin",)})
        self.assertEqual(restored.image_paths, {"PRIMARY": "legacy.jpg"})


if __name__ == "__main__":
    unittest.main()

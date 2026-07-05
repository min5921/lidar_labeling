from __future__ import annotations

import unittest

import numpy as np

from lidar_label_tool.calibration.waymo_camera import (
    CameraCalibration,
    camera_synced_projection_box,
    project_box_wireframe,
)
from lidar_label_tool.domain.labels import Box3D, LabeledObject


class WaymoCameraProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calibration = CameraCalibration(
            camera_id="FRONT",
            intrinsic=(100.0, 100.0, 320.0, 240.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            t_vehicle_camera=np.eye(4, dtype=np.float64),
            width=640,
            height=480,
        )

    def test_waymo_axis_direction_and_near_plane(self) -> None:
        uv, valid = self.calibration.project_vehicle_points(
            np.array(
                [
                    [10.0, 0.0, 0.0],
                    [10.0, -1.0, -2.0],
                    [-1.0, 0.0, 0.0],
                ],
                dtype=np.float64,
            )
        )
        np.testing.assert_allclose(uv[:2], [[320.0, 240.0], [330.0, 260.0]])
        np.testing.assert_array_equal(valid, [True, True, False])

    def test_box_wireframe_contains_twelve_edges_in_front_of_camera(self) -> None:
        wireframe = project_box_wireframe(
            "object-1",
            Box3D(x=10.0, y=0.0, z=0.0, length=2.0, width=2.0, height=2.0, yaw=0.0),
            self.calibration,
        )
        self.assertEqual(wireframe.object_id, "object-1")
        self.assertEqual(wireframe.segments.shape, (12, 2, 2))
        self.assertIsNotNone(wireframe.bounds)

    def test_wireframe_is_clipped_to_near_plane_and_image(self) -> None:
        wireframe = project_box_wireframe(
            "near-object",
            Box3D(x=0.4, y=0.0, z=0.0, length=1.0, width=4.0, height=2.0, yaw=0.0),
            self.calibration,
        )
        self.assertGreater(len(wireframe.segments), 0)
        self.assertTrue((wireframe.segments[:, :, 0] >= 0.0).all())
        self.assertTrue((wireframe.segments[:, :, 0] <= 639.0).all())
        self.assertTrue((wireframe.segments[:, :, 1] >= 0.0).all())
        self.assertTrue((wireframe.segments[:, :, 1] <= 479.0).all())

    def test_box_behind_camera_has_no_segments(self) -> None:
        wireframe = project_box_wireframe(
            "behind",
            Box3D(x=-10.0, y=0.0, z=0.0, length=2.0, width=2.0, height=2.0, yaw=0.0),
            self.calibration,
        )
        self.assertEqual(wireframe.segments.shape, (0, 2, 2))

    def test_camera_synced_box_keeps_user_edit_delta(self) -> None:
        obj = LabeledObject(
            id="object-1",
            class_name="Car",
            box3d=Box3D(x=11.0, y=2.0, z=1.0, length=5.0, width=2.0, height=2.0, yaw=0.2),
            source={
                "raw": {
                    "box": {
                        "center_x": 10.0,
                        "center_y": 2.0,
                        "center_z": 1.0,
                        "length": 4.0,
                        "width": 2.0,
                        "height": 2.0,
                        "heading": 0.1,
                    },
                    "camera_synced_box": {
                        "center_x": 10.2,
                        "center_y": 2.1,
                        "center_z": 1.0,
                        "length": 4.0,
                        "width": 2.0,
                        "height": 2.0,
                        "heading": 0.12,
                    },
                }
            },
        )
        projected = camera_synced_projection_box(obj)
        self.assertAlmostEqual(projected.x, 11.2)
        self.assertAlmostEqual(projected.y, 2.1)
        self.assertAlmostEqual(projected.length, 5.0)
        self.assertAlmostEqual(projected.yaw, 0.22)

    def test_generic_camera_calibration_direction(self) -> None:
        calibration = CameraCalibration.from_generic(
            "FRONT",
            {
                "intrinsic": [[100, 0, 320], [0, 100, 240], [0, 0, 1]],
                "T_camera_reference": np.eye(4).tolist(),
                "image_size": [640, 480],
                "distortion_model": "none",
            },
        )
        uv, valid = calibration.project_vehicle_points(
            np.array([[10.0, 0.0, 0.0]], dtype=np.float64)
        )
        np.testing.assert_allclose(uv, [[320.0, 240.0]])
        self.assertTrue(valid[0])


if __name__ == "__main__":
    unittest.main()

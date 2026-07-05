import math
import unittest

import numpy as np

from lidar_label_tool.domain.labels import Box3D
from lidar_label_tool.geometry.box3d import (
    bev_corners,
    box_contains_xy,
    box_corners_3d,
    side_rectangle,
)
from lidar_label_tool.geometry.transforms import invert_transform, transform_xyz, validate_rigid_transform


class GeometryTests(unittest.TestCase):
    def test_axis_aligned_box_corners(self) -> None:
        box = Box3D(0, 0, 1, 4, 2, 2, 0)
        corners = box_corners_3d(box)
        self.assertEqual(corners.shape, (8, 3))
        np.testing.assert_allclose(corners[:, 2].min(), 0)
        np.testing.assert_allclose(corners[:, 2].max(), 2)
        np.testing.assert_allclose(bev_corners(box)[0], [2, 1])
        np.testing.assert_allclose(side_rectangle(box, "xz"), [-2, 0, 2, 2])

    def test_yaw_rotation(self) -> None:
        box = Box3D(0, 0, 0, 4, 2, 2, math.pi / 2)
        corners = bev_corners(box)
        self.assertAlmostEqual(float(corners[:, 0].max()), 1.0)
        self.assertAlmostEqual(float(corners[:, 1].max()), 2.0)

    def test_rotated_bev_box_hit_test(self) -> None:
        box = Box3D(10, -3, 1, 4, 2, 2, math.pi / 2)

        self.assertTrue(box_contains_xy(box, 10, -1.1))
        self.assertTrue(box_contains_xy(box, 9.1, -3))
        self.assertFalse(box_contains_xy(box, 11.1, -3))
        self.assertFalse(box_contains_xy(box, 10, -0.9))

    def test_transform_and_inverse(self) -> None:
        transform = np.eye(4)
        transform[:3, 3] = [1, 2, 3]
        points = np.array([[0, 0, 0], [1, 1, 1]], dtype=np.float32)
        moved = transform_xyz(points, transform)
        restored = transform_xyz(moved, invert_transform(transform))
        np.testing.assert_allclose(restored, points)

    def test_rejects_non_rigid_transform(self) -> None:
        transform = np.eye(4)
        transform[0, 0] = 2
        with self.assertRaises(ValueError):
            validate_rigid_transform(transform)


if __name__ == "__main__":
    unittest.main()

import math
import unittest

import numpy as np

from lidar_label_tool.domain.labels import Box3D
from lidar_label_tool.geometry.box3d import bev_corners
from lidar_label_tool.geometry.box_edit import (
    move_box_xy,
    move_box_z,
    resize_box_from_corner,
    resize_box_height,
    rotate_box_toward,
)


class BoxEditGeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Box3D(10, -2, 1.5, 4, 2, 1.8, math.radians(30))

    def test_move_xy_preserves_non_planar_fields(self) -> None:
        moved = move_box_xy(self.box, 1.25, -0.75)

        self.assertAlmostEqual(moved.x, 11.25)
        self.assertAlmostEqual(moved.y, -2.75)
        self.assertEqual(moved.z, self.box.z)
        self.assertEqual(moved.length, self.box.length)
        self.assertEqual(moved.width, self.box.width)
        self.assertEqual(moved.height, self.box.height)
        self.assertEqual(moved.yaw, self.box.yaw)

    def test_corner_resize_keeps_opposite_corner_and_yaw(self) -> None:
        original_opposite = bev_corners(self.box)[2]
        resized = resize_box_from_corner(self.box, 0, 14, 2)

        np.testing.assert_allclose(bev_corners(resized)[2], original_opposite)
        self.assertEqual(resized.yaw, self.box.yaw)
        self.assertGreater(resized.length, 0)
        self.assertGreater(resized.width, 0)

    def test_corner_resize_clamps_minimum_size(self) -> None:
        fixed = bev_corners(self.box)[2]
        resized = resize_box_from_corner(
            self.box, 0, float(fixed[0] - 10), float(fixed[1] - 10)
        )

        self.assertAlmostEqual(resized.length, 0.05)
        self.assertAlmostEqual(resized.width, 0.05)

    def test_rotate_uses_radians_and_normalizes_yaw(self) -> None:
        rotated = rotate_box_toward(self.box, self.box.x - 1, self.box.y - 1)

        self.assertAlmostEqual(rotated.yaw, -3 * math.pi / 4)
        self.assertGreaterEqual(rotated.yaw, -math.pi)
        self.assertLess(rotated.yaw, math.pi)

    def test_move_z_preserves_horizontal_geometry(self) -> None:
        moved = move_box_z(self.box, 2.5)

        self.assertAlmostEqual(moved.z, 4.0)
        self.assertEqual(moved.x, self.box.x)
        self.assertEqual(moved.y, self.box.y)
        self.assertEqual(moved.length, self.box.length)
        self.assertEqual(moved.width, self.box.width)
        self.assertEqual(moved.height, self.box.height)
        self.assertEqual(moved.yaw, self.box.yaw)

    def test_height_resize_keeps_opposite_face_and_clamps(self) -> None:
        bottom = self.box.z - self.box.height / 2.0
        top = self.box.z + self.box.height / 2.0
        taller = resize_box_height(self.box, "top", top + 1.0)
        clamped = resize_box_height(self.box, "bottom", top + 10.0)

        self.assertAlmostEqual(taller.z - taller.height / 2.0, bottom)
        self.assertAlmostEqual(taller.height, self.box.height + 1.0)
        self.assertAlmostEqual(clamped.z + clamped.height / 2.0, top)
        self.assertAlmostEqual(clamped.height, 0.05)


if __name__ == "__main__":
    unittest.main()

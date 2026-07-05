from pathlib import Path
import unittest

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.ui.colors import point_rgba


def _cloud() -> PointCloudData:
    return PointCloudData(
        xyz=np.array([[0, 0, -1], [1, 0, 0], [2, 0, 3]], dtype=np.float32),
        attributes={"intensity": np.array([0.01, 1.0, 1000.0], dtype=np.float32)},
        sensor_id="TOP",
        return_id="1",
        source_frame="vehicle",
        source_path=Path("points.bin"),
    )


class PointColorTests(unittest.TestCase):
    def test_all_modes_return_rgba(self) -> None:
        cloud = _cloud()
        for mode in ("sensor", "height", "intensity", "uniform"):
            colors = point_rgba(cloud, mode, "#112233")
            self.assertEqual(colors.shape, (3, 4))
            self.assertTrue(np.isfinite(colors).all())

    def test_height_and_intensity_produce_gradients(self) -> None:
        cloud = _cloud()
        self.assertFalse(np.allclose(point_rgba(cloud, "height")[0], point_rgba(cloud, "height")[-1]))
        self.assertFalse(
            np.allclose(point_rgba(cloud, "intensity")[0], point_rgba(cloud, "intensity")[-1])
        )

    def test_uniform_hex_color(self) -> None:
        colors = point_rgba(_cloud(), "uniform", "#FF8000")
        np.testing.assert_allclose(colors[0, :3], [1.0, 128 / 255.0, 0.0])


if __name__ == "__main__":
    unittest.main()


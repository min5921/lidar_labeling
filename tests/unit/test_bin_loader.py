from pathlib import Path
import tempfile
import unittest

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudSpec
from lidar_label_tool.io.loaders.bin_loader import BinaryPointCloudLoader


class BinaryPointCloudLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = PointCloudSpec(
            columns=("x", "y", "z", "intensity", "elongation", "nlz_flag"),
            source_frame="vehicle",
        )

    def test_loads_nxc_and_filters_invalid_xyz(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points.bin"
            points = np.array(
                [
                    [1, 2, 3, 0.5, 1.0, 0.0],
                    [np.nan, 0, 0, 0.1, 2.0, 1.0],
                    [4, 5, 6, 0.9, 3.0, 0.0],
                ],
                dtype="<f4",
            )
            points.tofile(path)
            cloud = BinaryPointCloudLoader().load(
                path, self.spec, sensor_id="TOP", return_id="1"
            )
            self.assertEqual(cloud.point_count, 2)
            self.assertEqual(cloud.invalid_point_count, 1)
            self.assertEqual(set(cloud.attributes), {"intensity", "elongation", "nlz_flag"})
            np.testing.assert_allclose(cloud.xyz[1], [4, 5, 6])

    def test_rejects_misaligned_file_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.bin"
            path.write_bytes(b"12345")
            with self.assertRaises(ValueError):
                BinaryPointCloudLoader().load(
                    path, self.spec, sensor_id="TOP", return_id="1"
                )


if __name__ == "__main__":
    unittest.main()


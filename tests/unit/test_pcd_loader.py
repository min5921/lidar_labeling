from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudSpec
from lidar_label_tool.io.loaders.pcd_loader import PcdPointCloudLoader


class PcdPointCloudLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = PointCloudSpec(
            columns=("x", "y", "z", "intensity"), source_frame="vehicle"
        )

    def test_loads_ascii_pcd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points.pcd"
            path.write_text(
                "# .PCD v0.7\n"
                "VERSION 0.7\n"
                "FIELDS x y z intensity\n"
                "SIZE 4 4 4 4\n"
                "TYPE F F F F\n"
                "COUNT 1 1 1 1\n"
                "WIDTH 2\nHEIGHT 1\nPOINTS 2\nDATA ascii\n"
                "1 2 3 0.5\n4 5 6 0.9\n",
                encoding="ascii",
            )
            cloud = PcdPointCloudLoader().load(
                path, self.spec, sensor_id="MERGED", return_id="1"
            )
            np.testing.assert_allclose(cloud.xyz, [[1, 2, 3], [4, 5, 6]])
            np.testing.assert_allclose(cloud.attributes["intensity"], [0.5, 0.9])

    def test_loads_binary_pcd(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "points.pcd"
            header = (
                "VERSION 0.7\nFIELDS x y z intensity\nSIZE 4 4 4 4\n"
                "TYPE F F F F\nCOUNT 1 1 1 1\nWIDTH 1\nHEIGHT 1\n"
                "POINTS 1\nDATA binary\n"
            ).encode("ascii")
            with path.open("wb") as stream:
                stream.write(header)
                stream.write(np.array([[7, 8, 9, 1.5]], dtype="<f4").tobytes())
            cloud = PcdPointCloudLoader().load(
                path, self.spec, sensor_id="MERGED", return_id="1"
            )
            np.testing.assert_allclose(cloud.xyz, [[7, 8, 9]])
            np.testing.assert_allclose(cloud.attributes["intensity"], [1.5])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.services.dataset_discovery import discover_dataset


class DatasetDiscoveryTests(unittest.TestCase):
    def test_discovers_sensor_candidates_and_ignores_generated_folders(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 데이터 세트 01"
            _write(root / "sensors" / "lidar" / "AEVA" / "frames" / "000001.bin", b"x")
            _write(root / "raw lidar" / "LIDAR_POINTS" / "000002.pcd", b"pcd")
            _write(root / "camera" / "HEAD" / "images" / "000001.JPG", b"image")
            _write(root / "timestamps" / "AEVA.csv", b"sample_id,time_ns\n000001,1\n")
            _write(root / "annotations" / "fake" / "000001.bin", b"ignored")
            _write(root / "exports" / "fake" / "000001.jpg", b"ignored")

            result = discover_dataset(root)

            self.assertEqual(len(result.lidars), 2)
            self.assertEqual(len(result.cameras), 1)
            self.assertEqual(len(result.timestamps), 1)
            self.assertEqual(result.timestamps[0].columns, ("sample_id", "time_ns"))
            paths = {
                sample.relative_path
                for candidate in (*result.lidars, *result.cameras)
                for sample in candidate.samples
            }
            self.assertFalse(any(path.startswith("annotations/") for path in paths))
            self.assertFalse(any(path.startswith("exports/") for path in paths))
            self.assertTrue(all("{sample_id}" in item.data_pattern for item in result.lidars))
            self.assertTrue(result.cameras[0].data_pattern.endswith(".JPG"))

    def test_discovery_order_and_suggested_ids_are_deterministic(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write(root / "라이다 나" / "frames" / "b.bin", b"b")
            _write(root / "라이다 가" / "frames" / "a.bin", b"a")

            first = discover_dataset(root)
            second = discover_dataset(root)

            self.assertEqual(first, second)
            self.assertEqual(len({item.suggested_id for item in first.lidars}), 2)
            self.assertTrue(all(item.suggested_id.startswith("lidar_") for item in first.lidars))


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


if __name__ == "__main__":
    unittest.main()

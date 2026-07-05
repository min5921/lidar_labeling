from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData, PointCloudSpec
from lidar_label_tool.io.dataset import SourceFrameData
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.workers.frame_loader import load_frame_payload


class _PartialFailureAdapter:
    def __init__(self, source: SourceFrameData, failures: set[str]) -> None:
        self.source = source
        self.failures = failures

    def load_source_frame(self, frame_id: str) -> SourceFrameData:
        if frame_id != self.source.frame_id:
            raise KeyError(frame_id)
        return self.source

    def load_cloud_from_source(
        self, frame: SourceFrameData, sensor_id: str, return_id: str = "1"
    ) -> PointCloudData:
        key = f"{sensor_id}:return{return_id}"
        if key in self.failures:
            raise ValueError(f"broken cloud {key}")
        return PointCloudData(
            xyz=np.array([[1.0, 2.0, 3.0]], dtype=np.float32),
            attributes={},
            sensor_id=sensor_id,
            return_id=return_id,
            source_frame="vehicle",
            source_path=frame.point_cloud_paths[sensor_id][int(return_id) - 1],
        )


def _source(
    root: Path,
    *,
    with_image: bool = False,
    reference_paths: dict[str, Path] | None = None,
) -> SourceFrameData:
    return SourceFrameData(
        dataset_root=root,
        dataset_id="dataset",
        frame_id="000001",
        point_cloud_paths={
            "TOP": (root / "top_return1.bin", root / "top_return2.bin"),
            "FRONT": (root / "front_return1.bin",),
        },
        image_paths={"FRONT": root / "front.jpg"} if with_image else {},
        source_label_paths=reference_paths or {},
        point_spec=PointCloudSpec(
            columns=("x", "y", "z"), source_frame="vehicle"
        ),
        metadata={"reference_frame": "vehicle"},
    )


class FrameLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.importer = WaymoLabelImporter({})

    def test_one_return_failure_keeps_other_sensor_clouds(self) -> None:
        with TemporaryDirectory() as directory:
            source = _source(Path(directory))
            adapter = _PartialFailureAdapter(source, {"TOP:return2"})

            payload = load_frame_payload(adapter, self.importer, source.frame_id)

            self.assertEqual(len(payload.clouds["TOP"]), 1)
            self.assertEqual(len(payload.clouds["FRONT"]), 1)
            self.assertIn("TOP:return2", payload.sensor_errors)
            self.assertIn("ValueError: broken cloud", payload.sensor_errors["TOP:return2"])

    def test_all_lidar_failures_still_allow_camera_only_frame(self) -> None:
        with TemporaryDirectory() as directory:
            source = _source(Path(directory), with_image=True)
            failures = {"TOP:return1", "TOP:return2", "FRONT:return1"}

            payload = load_frame_payload(
                _PartialFailureAdapter(source, failures), self.importer, source.frame_id
            )

            self.assertEqual(payload.clouds, {})
            self.assertEqual(set(payload.sensor_errors), failures)

    def test_all_failures_without_other_useful_data_raise_clear_error(self) -> None:
        with TemporaryDirectory() as directory:
            source = _source(Path(directory))
            failures = {"TOP:return1", "TOP:return2", "FRONT:return1"}

            with self.assertRaisesRegex(RuntimeError, "no usable LiDAR cloud"):
                load_frame_payload(
                    _PartialFailureAdapter(source, failures),
                    self.importer,
                    source.frame_id,
                )

    def test_reference_layer_failure_is_reported_without_losing_clouds(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            camera_labels = root / "camera.json"
            camera_labels.write_text("{broken", encoding="utf-8")
            source = _source(root, reference_paths={"camera": camera_labels})

            payload = load_frame_payload(
                _PartialFailureAdapter(source, set()), self.importer, source.frame_id
            )

            self.assertIn("camera", payload.reference_layer_errors)
            self.assertIn("JSONDecodeError", payload.reference_layer_errors["camera"])


if __name__ == "__main__":
    unittest.main()

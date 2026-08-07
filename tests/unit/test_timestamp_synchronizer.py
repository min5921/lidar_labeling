from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.io.dataset_v2 import canonical_frame_index_bytes
from lidar_label_tool.services.timestamp_synchronizer import (
    SynchronizationError,
    logical_sample_id,
    make_sensor_samples,
    synchronize_profile,
)
from lidar_label_tool.services.timestamp_table import read_timestamp_table


class TimestampSynchronizerTests(unittest.TestCase):
    def test_nearest_preserves_every_lidar_and_uses_deterministic_tie_break(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lidar_table = _table(root / "lidar.csv", [("l0", 100), ("l1", 200), ("l2", 900)])
            camera_table = _table(
                root / "camera.csv",
                [("late", 110), ("early_b", 90), ("early_a", 90)],
            )
            lidars = make_sensor_samples(
                "aeva",
                (("l0", "lidar/l0.bin"), ("l1", "lidar/l1.bin"), ("l2", "lidar/l2.bin")),
            )
            cameras = make_sensor_samples(
                "head_camera",
                (
                    ("late", "camera/z.jpg"),
                    ("early_b", "camera/b.jpg"),
                    ("early_a", "camera/a.jpg"),
                ),
            )

            result = synchronize_profile(
                profile_id="aeva_profile",
                lidar_samples=lidars,
                method="timestamp_nearest",
                camera_samples=cameras,
                lidar_timestamps=lidar_table,
                camera_timestamps=camera_table,
                tolerance_ns=50,
            )
            repeated = synchronize_profile(
                profile_id="aeva_profile",
                lidar_samples=tuple(reversed(lidars)),
                method="timestamp_nearest",
                camera_samples=tuple(reversed(cameras)),
                lidar_timestamps=lidar_table,
                camera_timestamps=camera_table,
                tolerance_ns=50,
            )

            self.assertEqual(len(result.records), 3)
            self.assertEqual(result.records[0].camera.source_sample_id, "early_a")  # type: ignore[union-attr]
            self.assertIsNone(result.records[1].camera)
            self.assertIsNone(result.records[2].camera)
            self.assertEqual(result.qa.unmatched_camera_count, 2)
            self.assertEqual(
                canonical_frame_index_bytes(result.records),
                canonical_frame_index_bytes(repeated.records),
            )

    def test_camera_reuse_is_allowed_and_reported(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lidar_table = _table(root / "lidar.csv", [("a", 100), ("b", 101), ("c", 102)])
            camera_table = _table(root / "camera.csv", [("image", 101)])
            result = synchronize_profile(
                profile_id="profile",
                lidar_samples=make_sensor_samples(
                    "lidar", ((value, f"lidar/{value}.bin") for value in "abc")
                ),
                method="timestamp_nearest",
                camera_samples=make_sensor_samples(
                    "camera", (("image", "camera/image.jpg"),)
                ),
                lidar_timestamps=lidar_table,
                camera_timestamps=camera_table,
                tolerance_ns=2,
            )
            self.assertEqual(result.qa.camera_sample_reuse_count, 2)
            self.assertEqual(result.qa.max_camera_repeat_run, 3)

    def test_clock_mismatch_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lidar_table = _table(root / "lidar.csv", [("a", 1)], clock="bag")
            camera_table = _table(root / "camera.csv", [("a", 1)], clock="device")
            with self.assertRaises(SynchronizationError) as raised:
                synchronize_profile(
                    profile_id="profile",
                    lidar_samples=make_sensor_samples("lidar", (("a", "a.bin"),)),
                    method="timestamp_nearest",
                    camera_samples=make_sensor_samples("camera", (("a", "a.jpg"),)),
                    lidar_timestamps=lidar_table,
                    camera_timestamps=camera_table,
                    tolerance_ns=1,
                )
            self.assertEqual(raised.exception.code, "clock_domain_mismatch")

    def test_unsafe_source_sample_id_uses_stable_hash(self) -> None:
        first = logical_sample_id("aeva", "한글 sample 1", "센서/한글 sample 1.bin")
        second = logical_sample_id("aeva", "한글 sample 1", "센서/한글 sample 1.bin")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)
        self.assertTrue(first.startswith("s_"))


def _table(
    path: Path,
    rows: list[tuple[str, int]],
    *,
    clock: str = "bag",
):
    path.write_text(
        "sample_id,time_ns\n"
        + "".join(f"{sample_id},{timestamp}\n" for sample_id, timestamp in rows),
        encoding="utf-8",
    )
    return read_timestamp_table(
        path,
        sample_id_column="sample_id",
        value_column="time_ns",
        unit="ns",
        clock_domain=clock,
    )


if __name__ == "__main__":
    unittest.main()

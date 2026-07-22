from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

from lidar_label_tool.app.packaged import dataset_argument


class PackagedAppTests(unittest.TestCase):
    def test_dataset_argument_ignores_smoke_test_flag(self) -> None:
        with patch.object(Path, "cwd", return_value=Path("/work")):
            self.assertEqual(
                dataset_argument(["LiDARLabelTool", "--smoke-test", "dataset"]),
                Path("/work/dataset"),
            )

    def test_dataset_argument_accepts_quoted_absolute_path(self) -> None:
        absolute = Path.cwd() / "one chip converted"
        self.assertEqual(
            dataset_argument(["LiDARLabelTool", f'"{absolute}"']),
            absolute,
        )

    def test_dataset_argument_is_optional(self) -> None:
        self.assertIsNone(dataset_argument(["LiDARLabelTool"]))

from __future__ import annotations

import unittest

from lidar_label_tool.app.cli import _parser


class CliTests(unittest.TestCase):
    def test_gui_dataset_is_optional_for_folder_picker(self) -> None:
        args = _parser().parse_args(["gui"])
        self.assertEqual(args.command, "gui")
        self.assertIsNone(args.dataset)

    def test_export_arguments(self) -> None:
        args = _parser().parse_args(
            [
                "export",
                "dataset",
                "--format",
                "centerpoint_intermediate_json",
                "--output",
                "exported",
                "--frame",
                "000001",
                "--frame",
                "000002",
            ]
        )
        self.assertEqual(args.command, "export")
        self.assertEqual(args.frames, ["000001", "000002"])
        self.assertEqual(args.export_format, "centerpoint_intermediate_json")


if __name__ == "__main__":
    unittest.main()

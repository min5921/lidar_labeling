from __future__ import annotations

import unittest

from lidar_label_tool.app.cli import _parser


class CliTests(unittest.TestCase):
    def test_gui_dataset_is_optional_for_folder_picker(self) -> None:
        args = _parser().parse_args(["gui"])
        self.assertEqual(args.command, "gui")
        self.assertIsNone(args.dataset)


if __name__ == "__main__":
    unittest.main()

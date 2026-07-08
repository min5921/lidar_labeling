from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.app.cli import _parser, main
from tests.fixture_builders import create_device_dataset, source_object, write_source_labels


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

    def test_preflight_json_output_and_valid_exit_code(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["preflight", str(root), "--json"])

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["dataset_id"], "preflight_fixture")
            self.assertEqual(payload["frame_count"], 1)
            self.assertIn("issues", payload)
            self.assertEqual(payload["frame_cameras"], {"000000": []})
            self.assertEqual(payload["issue_counts"]["error"], 0)

    def test_preflight_warning_and_error_exit_codes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            camera_manifest = json.loads((root / "dataset.json").read_text(encoding="utf-8"))
            camera_manifest["sensors"].append(
                {
                    "id": "FRONT",
                    "type": "camera",
                    "coordinate_frame": "camera:FRONT",
                    "data_patterns": {"image": "sensors/camera/FRONT/{sample_id}.png"},
                }
            )
            (root / "dataset.json").write_text(
                json.dumps(camera_manifest), encoding="utf-8"
            )
            output = StringIO()
            with redirect_stdout(output):
                warning_exit = main(["preflight", str(root), "--json"])
            self.assertEqual(warning_exit, 1)

            (root / "sensors" / "lidar" / "MERGED" / "000000.bin").unlink()
            output = StringIO()
            with redirect_stdout(output):
                error_exit = main(["preflight", str(root), "--json"])
            self.assertEqual(error_exit, 2)

    def test_stats_json_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_device_dataset(root)
            write_source_labels(root, "000000", [source_object("car-1")])
            output = StringIO()

            with redirect_stdout(output):
                exit_code = main(["stats", str(root), "--json"])

            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["mode"], "source")
            self.assertEqual(payload["object_count"], 1)
            self.assertEqual(payload["class_counts"], {"Car": 1})


if __name__ == "__main__":
    unittest.main()

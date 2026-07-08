from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.exporters import (
    CenterPointIntermediateJsonExporter,
    ExporterRegistry,
    LidarLabelJsonExporter,
    create_default_registry,
    export_frames,
)


def _label(frame_id: str = "000007") -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset",
        frame_id=frame_id,
        point_cloud_paths={"MERGED": (f"sensors/MERGED/{frame_id}.bin",)},
        image_paths={"FRONT": f"sensors/FRONT/{frame_id}.jpg"},
        reference_frame="vehicle",
        objects=(
            LabeledObject(
                id="source-id",
                class_name="Car",
                box3d=Box3D(10, 2, 1, 4.2, 1.8, 1.6, 0.25),
                attributes={"unknown_attribute": "preserved"},
                source={"format": "fixture", "unknown_source_field": 42},
            ),
        ),
        frame_status="in_progress",
        provenance={
            "source_format": "none",
            "source_paths": [],
            "source_fingerprints": {},
        },
        calibration_state={
            "mode": "auto",
            "fingerprint": None,
            "sensor_status": {},
        },
    )


class ExporterTests(unittest.TestCase):
    def test_default_registry_lookup(self) -> None:
        registry = create_default_registry()

        exporter = registry.get("lidar_label_json")

        self.assertIsInstance(exporter, LidarLabelJsonExporter)
        self.assertEqual(
            registry.names,
            ("centerpoint_intermediate_json", "lidar_label_json"),
        )

    def test_registry_rejects_duplicate_name(self) -> None:
        registry = ExporterRegistry()
        registry.register(LidarLabelJsonExporter())

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(LidarLabelJsonExporter())

    def test_json_export_round_trip_preserves_internal_label(self) -> None:
        label = _label()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "000007.json"

            LidarLabelJsonExporter().export_frame(label, output)

            raw = json.loads(output.read_text(encoding="utf-8"))
            restored = FrameLabel.from_dict(raw)
            self.assertEqual(restored, label)
            self.assertEqual(raw["objects"][0]["source"]["unknown_source_field"], 42)

    def test_centerpoint_intermediate_json_structure_uses_radians(self) -> None:
        label = _label()
        with TemporaryDirectory() as directory:
            output = Path(directory) / "000007.json"

            CenterPointIntermediateJsonExporter().export_frame(label, output)

            raw = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(raw["format"], "centerpoint_intermediate_json")
            self.assertEqual(raw["yaw_unit"], "radians")
            self.assertEqual(raw["objects"][0]["object_id"], "source-id")
            self.assertEqual(raw["objects"][0]["class_name"], "Car")
            self.assertEqual(raw["objects"][0]["box3d"]["center"], {"x": 10, "y": 2, "z": 1})
            self.assertAlmostEqual(raw["objects"][0]["box3d"]["yaw"], 0.25)

    def test_batch_export_writes_one_file_per_frame(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "export"

            paths = export_frames(
                (_label("000007"), _label("000008")),
                CenterPointIntermediateJsonExporter(),
                output,
            )

            self.assertEqual([path.name for path in paths], ["000007.json", "000008.json"])
            self.assertEqual(
                json.loads(paths[1].read_text(encoding="utf-8"))["frame_id"], "000008"
            )

    def test_invalid_dimension_and_nan_yaw_are_rejected_before_write(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "label.json"
            output.write_text("preserved", encoding="utf-8")
            invalid_size = _label()
            object.__setattr__(invalid_size.objects[0].box3d, "length", -1.0)

            with self.assertRaisesRegex(ValueError, "length must be positive"):
                LidarLabelJsonExporter({"Car"}).export_frame(invalid_size, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "preserved")

            invalid_yaw = _label()
            object.__setattr__(invalid_yaw.objects[0].box3d, "yaw", float("nan"))
            with self.assertRaisesRegex(ValueError, "yaw must be finite"):
                CenterPointIntermediateJsonExporter({"Car"}).export_frame(
                    invalid_yaw, output
                )
            self.assertEqual(output.read_text(encoding="utf-8"), "preserved")

    def test_unknown_class_policy(self) -> None:
        label = _label()
        alien = replace(label.objects[0], class_name="Alien")
        unknown = replace(label.objects[0], class_name="Unknown")
        exporter = LidarLabelJsonExporter({"Car"}, allow_unknown=True)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "label.json"

            with self.assertRaisesRegex(ValueError, "unknown class_name"):
                exporter.export_frame(replace(label, objects=(alien,)), output)
            exporter.export_frame(replace(label, objects=(unknown,)), output)
            self.assertTrue(output.is_file())

    def test_batch_prevalidation_prevents_partial_output(self) -> None:
        valid = _label("000007")
        invalid = _label("000008")
        object.__setattr__(invalid.objects[0].box3d, "width", 0.0)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "export"

            with self.assertRaisesRegex(ValueError, "width must be positive"):
                export_frames(
                    (valid, invalid),
                    CenterPointIntermediateJsonExporter({"Car"}),
                    output,
                )

            self.assertFalse((output / "000007.json").exists())


if __name__ == "__main__":
    unittest.main()

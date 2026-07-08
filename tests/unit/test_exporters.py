from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.exporters import (
    ExporterRegistry,
    LidarLabelJsonExporter,
    create_default_registry,
)


def _label() -> FrameLabel:
    return FrameLabel(
        dataset_id="dataset",
        frame_id="000007",
        point_cloud_paths={"MERGED": ("sensors/MERGED/000007.bin",)},
        image_paths={"FRONT": "sensors/FRONT/000007.jpg"},
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


if __name__ == "__main__":
    unittest.main()

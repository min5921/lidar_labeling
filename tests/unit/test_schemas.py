import json
from pathlib import Path
import unittest

try:
    import jsonschema
except ImportError:  # Core-only environments may omit optional validation dependencies.
    jsonschema = None

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(jsonschema is None, "jsonschema optional dependency is not installed")
class JsonSchemaTests(unittest.TestCase):
    def test_all_project_schemas_are_valid_draft_2020_12(self) -> None:
        for path in (ROOT / "schemas").glob("*.json"):
            schema = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)

    def test_default_config_matches_schema(self) -> None:
        config = json.loads((ROOT / "configs" / "default.json").read_text(encoding="utf-8"))
        schema = json.loads(
            (ROOT / "schemas" / "config.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.validate(config, schema)

    def test_saved_frame_shape_matches_schema(self) -> None:
        label = FrameLabel(
            dataset_id="dataset",
            frame_id="frame_000",
            point_cloud_paths={"TOP": ("top.bin",)},
            image_paths={"FRONT": "front.jpg"},
            reference_frame="vehicle",
            revision=1,
            objects=(LabeledObject("id", "Car", Box3D(0, 0, 0, 4, 2, 2, 0)),),
        )
        schema = json.loads(
            (ROOT / "schemas" / "label.schema.json").read_text(encoding="utf-8")
        )
        jsonschema.validate(label.to_dict(), schema)


if __name__ == "__main__":
    unittest.main()

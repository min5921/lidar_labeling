import json
from copy import deepcopy
from pathlib import Path
import unittest

try:
    import jsonschema
except ImportError:  # Core-only environments may omit optional validation dependencies.
    jsonschema = None

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject


ROOT = Path(__file__).resolve().parents[2]
SHA256_ZERO = "0" * 64


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))


def _dataset_v2() -> dict:
    return {
        "schema_version": "2.0",
        "dataset_id": "ds_7d30c92f",
        "display_name": "광기술원 동적 차량 데이터",
        "manifest_revision": 1,
        "layout": "device_centric_v2",
        "data_root": {"kind": "manifest_relative", "path": "."},
        "coordinate_system": {
            "unit": "meter",
            "x_axis": "forward",
            "y_axis": "left",
            "z_axis": "up",
            "yaw_axis": "+z",
            "yaw_unit": "radian",
            "yaw_zero": "+x",
            "yaw_direction": "counterclockwise",
            "box_center": "geometric_center",
        },
        "labeling_policy": {
            "active_lidar": "one_per_profile",
            "merge_lidars": False,
            "label_namespace": "profile_lidar",
            "frame_id_policy": "logical_lidar_sample_id",
        },
        "lidars": [
            {
                "id": "aeva",
                "display_name": "AEVA",
                "coordinate_frame": "lidar:AEVA",
                "format": "bin",
                "data_pattern": "sensors/lidar/AEVA/frames/{sample_id}.bin",
                "point_columns": ["x", "y", "z", "velocity", "intensity"],
                "point_dtype": "float32",
                "byte_order": "little-endian",
                "timestamp": {
                    "format": "csv",
                    "path": "timestamps/AEVA.csv",
                    "sample_id_column": "sample_id",
                    "value_column": "bag_time_ns",
                    "unit": "ns",
                    "clock_domain": "bag",
                    "offset_ns": 0,
                    "sha256": SHA256_ZERO,
                },
            }
        ],
        "camera": {
            "id": "head_camera",
            "display_name": "HEAD_CAMERA",
            "coordinate_frame": "camera:HEAD_CAMERA",
            "image_pattern": "sensors/camera/HEAD_CAMERA/images/{sample_id}.jpg",
            "timestamp": {
                "format": "csv",
                "path": "timestamps/HEAD_CAMERA.csv",
                "sample_id_column": "sample_id",
                "value_column": "bag_time_ns",
                "unit": "ns",
                "clock_domain": "bag",
                "offset_ns": 0,
                "sha256": SHA256_ZERO,
            },
        },
        "profiles": [
            {
                "id": "aeva_profile",
                "display_name": "AEVA 라벨링",
                "lidar_id": "aeva",
                "camera": {
                    "camera_id": "head_camera",
                    "mode": "display_only",
                    "calibration_path": None,
                    "calibration_sha256": None,
                },
                "frame_index": {
                    "schema_version": "2.0",
                    "path": "generations/generation-000001/sync/aeva_profile.frames.jsonl",
                    "sha256": SHA256_ZERO,
                    "frame_count": 216,
                    "generation": {
                        "method": "timestamp_nearest",
                        "tolerance_ns": 50_000_000,
                    },
                },
            }
        ],
        "default_profile_id": "aeva_profile",
        "taxonomy": {
            "schema_version": "2.0",
            "path": "generations/generation-000001/taxonomy.json",
            "sha256": SHA256_ZERO,
        },
    }


def _label_v2() -> dict:
    return {
        "schema_version": "2.0",
        "dataset_id": "ds_7d30c92f",
        "profile_id": "aeva_profile",
        "label_lidar_id": "aeva",
        "frame_id": "000000",
        "label_lidar_sample_id": "000000",
        "revision": 1,
        "frame_status": "in_progress",
        "saved_at_utc": "2026-08-07T01:23:45Z",
        "point_cloud_path": "sensors/lidar/AEVA/frames/000000.bin",
        "image_path": "sensors/camera/HEAD_CAMERA/images/000000.jpg",
        "reference_frame": "lidar:AEVA",
        "coordinate_system": {
            "unit": "meter",
            "x_axis": "forward",
            "y_axis": "left",
            "z_axis": "up",
            "yaw_axis": "+z",
            "yaw_unit": "radian",
            "yaw_zero": "+x",
            "yaw_direction": "counterclockwise",
            "box_center": "geometric_center",
        },
        "provenance": {
            "source_format": "device_centric_v2",
            "source_paths": [],
            "source_fingerprints": {},
            "dataset_manifest": {"path": "dataset.json", "sha256": SHA256_ZERO},
            "profile_sha256": SHA256_ZERO,
            "frame_index": {
                "path": "generations/generation-000001/sync/aeva_profile.frames.jsonl",
                "sha256": SHA256_ZERO,
                "lidar_binding_sha256": SHA256_ZERO,
                "frame_record_sha256": SHA256_ZERO,
            },
            "taxonomy": {
                "path": "generations/generation-000001/taxonomy.json",
                "sha256": SHA256_ZERO,
            },
            "point_cloud_sha256": SHA256_ZERO,
            "image_sha256": SHA256_ZERO,
        },
        "calibration_state": {
            "requested_mode": "display_only",
            "effective_mode": "display_only",
            "path": None,
            "fingerprint": None,
            "status": "not_configured",
        },
        "objects": [
            {
                "id": "object_001",
                "class_id": "car",
                "box3d": {
                    "x": 10.0,
                    "y": 1.0,
                    "z": 0.8,
                    "length": 4.2,
                    "width": 1.8,
                    "height": 1.6,
                    "yaw": 0.0,
                },
            }
        ],
    }


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

    def test_generic_dataset_v2_example_matches_schema(self) -> None:
        jsonschema.validate(_dataset_v2(), _schema("dataset-v2.schema.json"))

    def test_generic_dataset_v2_accepts_lidar_only_and_pcd(self) -> None:
        dataset = _dataset_v2()
        dataset["camera"] = None
        dataset["profiles"][0]["camera"] = None
        dataset["profiles"][0]["frame_index"]["generation"] = {
            "method": "lidar_only",
            "tolerance_ns": None,
        }
        lidar = dataset["lidars"][0]
        lidar["format"] = "pcd"
        lidar["data_pattern"] = "한글 데이터/lidar/{sample_id}.PCD"
        del lidar["point_dtype"]
        del lidar["byte_order"]

        jsonschema.validate(dataset, _schema("dataset-v2.schema.json"))

        external = deepcopy(dataset)
        external["data_root"] = {
            "kind": "absolute_local",
            "path": "C:\\한글 데이터\\원본",
        }
        jsonschema.validate(external, _schema("dataset-v2.schema.json"))

    def test_generic_dataset_v2_rejects_unsafe_or_ambiguous_contracts(self) -> None:
        schema = _schema("dataset-v2.schema.json")

        uppercase_id = deepcopy(_dataset_v2())
        uppercase_id["lidars"][0]["id"] = "AEVA"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(uppercase_id, schema)

        missing_z = deepcopy(_dataset_v2())
        missing_z["lidars"][0]["point_columns"] = ["x", "y", "intensity"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(missing_z, schema)

        missing_tolerance = deepcopy(_dataset_v2())
        del missing_tolerance["profiles"][0]["frame_index"]["generation"][
            "tolerance_ns"
        ]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(missing_tolerance, schema)

        multiple_cameras = deepcopy(_dataset_v2())
        multiple_cameras["camera"] = [multiple_cameras["camera"]]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(multiple_cameras, schema)

        windows_reserved_id = deepcopy(_dataset_v2())
        windows_reserved_id["profiles"][0]["id"] = "con"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(windows_reserved_id, schema)

        escaped_path = deepcopy(_dataset_v2())
        escaped_path["lidars"][0]["timestamp"]["path"] = "../timestamps/AEVA.csv"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(escaped_path, schema)

        relative_absolute_root = deepcopy(_dataset_v2())
        relative_absolute_root["data_root"] = {
            "kind": "absolute_local",
            "path": "relative/data",
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(relative_absolute_root, schema)

        unknown_placeholder = deepcopy(_dataset_v2())
        unknown_placeholder["lidars"][0]["data_pattern"] = (
            "sensors/{sensor_id}/{sample_id}.bin"
        )
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(unknown_placeholder, schema)

        null_camera_with_profile_camera = deepcopy(_dataset_v2())
        null_camera_with_profile_camera["camera"] = None
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(null_camera_with_profile_camera, schema)

    def test_frame_index_v2_example_matches_schema(self) -> None:
        record = {
            "schema_version": "2.0",
            "profile_id": "aeva_profile",
            "ordinal": 0,
            "frame_id": "000000",
            "lidar": {
                "sensor_id": "aeva",
                "sample_id": "000000",
                "source_sample_id": "000000",
                "path": "sensors/lidar/AEVA/frames/000000.bin",
                "timestamp_ns": 1_778_225_784_354_747_202,
            },
            "camera": {
                "sensor_id": "head_camera",
                "sample_id": "000000",
                "source_sample_id": "000000",
                "path": "sensors/camera/HEAD_CAMERA/images/000000.jpg",
                "timestamp_ns": 1_778_225_784_347_166_083,
                "delta_ns": -7_581_119,
            },
            "match": {
                "method": "timestamp_nearest",
                "status": "matched",
                "tolerance_ns": 50_000_000,
            },
        }
        jsonschema.validate(record, _schema("frame-index-v2.schema.json"))

    def test_frame_index_v2_enforces_match_shape(self) -> None:
        schema = _schema("frame-index-v2.schema.json")
        lidar_only = {
            "schema_version": "2.0",
            "profile_id": "aeva_profile",
            "ordinal": 0,
            "frame_id": "000000",
            "lidar": {
                "sensor_id": "aeva",
                "sample_id": "000000",
                "source_sample_id": "원본 000000",
                "path": "한글 데이터/sensors/AEVA/000000.bin",
                "timestamp_ns": None,
            },
            "camera": None,
            "match": {
                "method": "lidar_only",
                "status": "not_requested",
                "tolerance_ns": None,
            },
        }
        jsonschema.validate(lidar_only, schema)

        invalid_match = deepcopy(lidar_only)
        invalid_match["match"]["status"] = "matched"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(invalid_match, schema)

    def test_label_v2_requires_profile_and_lidar_identity(self) -> None:
        schema = _schema("label-v2.schema.json")
        jsonschema.validate(_label_v2(), schema)

        missing_identity = _label_v2()
        del missing_identity["label_lidar_id"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(missing_identity, schema)

        invalid_calibration = _label_v2()
        invalid_calibration["calibration_state"]["effective_mode"] = "calibrated"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(invalid_calibration, schema)

        unsafe_fingerprint_key = _label_v2()
        unsafe_fingerprint_key["provenance"]["source_fingerprints"] = {
            "../outside.bin": SHA256_ZERO
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(unsafe_fingerprint_key, schema)

    def test_label_v2_migration_provenance_is_explicit(self) -> None:
        schema = _schema("label-v2.schema.json")
        migrated = _label_v2()
        migrated["revision"] = 5
        migrated["provenance"]["migration"] = {
            "from_schema_version": "1.0",
            "source_path": "annotations/lidar_label_tool/000000.json",
            "source_sha256": SHA256_ZERO,
            "source_revision": 4,
            "migrated_at_utc": "2026-08-07T01:23:45Z",
            "tool_version": "0.2.0",
            "legacy_dataset_id": "한글 데이터",
            "class_mapping_sha256": SHA256_ZERO,
        }
        jsonschema.validate(migrated, schema)

        missing_mapping = deepcopy(migrated)
        del missing_mapping["provenance"]["migration"]["class_mapping_sha256"]
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(missing_mapping, schema)

    def test_recovery_and_session_lock_v2_scope(self) -> None:
        recovery = {
            "schema_version": "2.0",
            "kind": "label_recovery",
            "dataset_id": "ds_7d30c92f",
            "profile_id": "aeva_profile",
            "label_lidar_id": "aeva",
            "frame_id": "000000",
            "reference_frame": "lidar:AEVA",
            "profile_sha256": SHA256_ZERO,
            "base_revision": 1,
            "base_label_sha256": SHA256_ZERO,
            "created_at_utc": "2026-08-07T01:24:00Z",
            "label": _label_v2(),
        }
        jsonschema.validate(recovery, _schema("recovery-v2.schema.json"))

        session_lock = {
            "schema_version": "2.0",
            "kind": "profile_session_lock",
            "dataset_id": "ds_7d30c92f",
            "profile_id": "aeva_profile",
            "label_lidar_id": "aeva",
            "reference_frame": "lidar:AEVA",
            "profile_sha256": SHA256_ZERO,
            "pid": 1234,
            "host": "label-pc-01",
            "owner": "operator",
            "started_at_utc": "2026-08-07T01:24:00Z",
            "heartbeat_at_utc": "2026-08-07T01:24:10Z",
            "tool_version": "0.2.0",
            "nonce": "0" * 32,
        }
        lock_schema = _schema("session-lock-v2.schema.json")
        jsonschema.validate(session_lock, lock_schema)

        frame_scoped_lock = deepcopy(session_lock)
        frame_scoped_lock["frame_id"] = "000000"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(frame_scoped_lock, lock_schema)

    def test_taxonomy_v2_example_matches_schema(self) -> None:
        taxonomy = {
            "schema_version": "2.0",
            "display_name": "기본 객체 클래스",
            "classes": [
                {
                    "id": "car",
                    "display_name": "자동차",
                    "color": "#00D084",
                    "default_size_m": {
                        "length": 4.2,
                        "width": 1.8,
                        "height": 1.6,
                    },
                    "shortcut": "1",
                    "aliases": ["Vehicle"],
                }
            ],
            "fallback_class_id": "car",
            "source_mappings": {"waymo": {"TYPE_VEHICLE": "car"}},
        }
        jsonschema.validate(taxonomy, _schema("taxonomy.schema.json"))


if __name__ == "__main__":
    unittest.main()

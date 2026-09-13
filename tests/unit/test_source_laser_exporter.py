from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.exporters import (
    SourceLaserJsonExporter,
    create_default_registry,
    export_frames,
)
from lidar_label_tool.exporters.source_laser_json import DEFAULT_SOURCE_CLASS_MAPPING
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter


def _raw_object() -> dict:
    return {
        "id": "source-string-001",
        "type": "TYPE_SIGN",
        "box": {
            "center_x": 12.0, "center_y": -3.0, "center_z": 4.5,
            "length": 1.2, "width": 0.3, "height": 0.9, "heading": -0.25,
            "unknown_box": {"note": "preserve"},
        },
        "metadata": {"speed_x": 2.5, "unknown": [1, {"한글": "유지"}]},
        "num_lidar_points_in_box": 24,
        "detection_difficulty_level": "LEVEL_2",
        "unknown_object": {"nested": [7, 8]},
    }


def _label(raw: dict | None = None) -> FrameLabel:
    importer = WaymoLabelImporter(DEFAULT_SOURCE_CLASS_MAPPING)
    return FrameLabel(
        dataset_id="dataset", frame_id="000001", reference_frame="vehicle",
        point_cloud_paths={"MERGED": ("lidar/000001.bin",)}, image_paths={},
        objects=importer.import_laser_objects((_raw_object() if raw is None else raw,)),
    )


def test_source_array_roundtrip_preserves_id_unknown_fields_and_center(tmp_path: Path) -> None:
    label = _label()
    before = deepcopy(label.to_dict())
    output = tmp_path / "한글 폴더" / "laser_labels.json"
    exporter = SourceLaserJsonExporter()
    exporter.export_frame(label, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert payload == [_raw_object()]
    restored = WaymoLabelImporter(DEFAULT_SOURCE_CLASS_MAPPING).import_laser_objects(payload)
    assert restored[0].id == label.objects[0].id
    assert restored[0].box3d == label.objects[0].box3d
    assert restored[0].box3d.z == 4.5  # Elevated signs stay at geometric center.
    assert restored[0].attributes == label.objects[0].attributes
    assert label.to_dict() == before


def test_edits_update_box_class_attributes_and_current_linked_id(tmp_path: Path) -> None:
    label = _label()
    obj = replace(
        label.objects[0], id="linked-uuid", class_name="Car",
        box3d=Box3D(14, -4, 2, 4.5, 1.8, 1.6, 0.4),
        attributes={"speed_x": 3.5, "occluded": True, "num_lidar_points_in_box": 50},
        extra_fields={"object_link_history": [{"previous_id": "source-string-001"}]},
    )
    changed = replace(label, objects=(obj,))
    exporter = SourceLaserJsonExporter()
    report = exporter.describe(changed)
    assert report.changed_id_object_ids == ("linked-uuid",)
    assert report.changed_type_object_ids == ("linked-uuid",)
    assert "linked-uuid.object_link_history" in report.omitted_object_fields
    assert "revision" in report.omitted_frame_fields
    assert json.loads(json.dumps(report.to_dict()))["frame_id"] == label.frame_id
    output = tmp_path / "label.json"
    exporter.export_frame(changed, output)
    raw = json.loads(output.read_text(encoding="utf-8"))[0]
    assert raw["id"] == "linked-uuid"
    assert raw["type"] == "TYPE_VEHICLE"
    assert raw["metadata"] == {"speed_x": 3.5, "occluded": True}
    assert raw["num_lidar_points_in_box"] == 50
    assert "detection_difficulty_level" not in raw
    assert raw["unknown_object"] == _raw_object()["unknown_object"]
    assert raw["box"]["unknown_box"] == _raw_object()["box"]["unknown_box"]


def test_importer_shadowed_metadata_is_preserved_without_masking_edit(tmp_path: Path) -> None:
    raw = _raw_object()
    raw["metadata"]["num_lidar_points_in_box"] = "shadowed-original"
    label = _label(raw)
    obj = replace(label.objects[0], attributes={**label.objects[0].attributes,
                                               "num_lidar_points_in_box": 99})
    output = tmp_path / "label.json"
    SourceLaserJsonExporter().export_frame(replace(label, objects=(obj,)), output)
    result = json.loads(output.read_text(encoding="utf-8"))[0]
    assert result["metadata"]["num_lidar_points_in_box"] == "shadowed-original"
    assert result["num_lidar_points_in_box"] == 99


def test_source_type_disambiguates_many_to_one_import_mapping(tmp_path: Path) -> None:
    mapping = {"TYPE_CAR": "Car", "TYPE_TRUCK": "Car"}
    raw = _raw_object()
    raw["type"] = "TYPE_TRUCK"
    obj = WaymoLabelImporter(mapping).import_laser_objects((raw,))[0]
    label = replace(_label(), objects=(obj,))
    exporter = SourceLaserJsonExporter(source_class_mapping=mapping)
    output = tmp_path / "label.json"
    exporter.export_frame(label, output)
    assert json.loads(output.read_text(encoding="utf-8"))[0]["type"] == "TYPE_TRUCK"
    fresh = replace(label, objects=(replace(obj, id="new", source={}),))
    with pytest.raises(ValueError, match="ambiguous source class mapping"):
        exporter.export_frame(fresh, tmp_path / "ambiguous.json")
    assert not (tmp_path / "ambiguous.json").exists()


def test_explicit_mapping_supports_custom_taxonomy_and_is_authoritative(tmp_path: Path) -> None:
    obj = replace(_label().objects[0], class_name="vehicle", source={})
    label = replace(_label(), objects=(obj,))
    with pytest.raises(ValueError, match="unmapped source class mapping"):
        SourceLaserJsonExporter().validate(label)
    registry = create_default_registry(
        {"vehicle"}, source_class_mapping={},
        export_class_mapping={"vehicle": "TYPE_CUSTOM_VEHICLE"},
    )
    output = tmp_path / "label.json"
    registry.get("source_laser_json").export_frame(label, output)
    assert json.loads(output.read_text(encoding="utf-8"))[0]["type"] == "TYPE_CUSTOM_VEHICLE"
    original_sign = _label()
    explicit = SourceLaserJsonExporter(export_class_mapping={"Sign": "TYPE_CUSTOM_SIGN"})
    explicit.export_frame(original_sign, tmp_path / "explicit.json")
    assert explicit.describe(original_sign).changed_type_object_ids == (original_sign.objects[0].id,)


def test_unrecognized_source_type_stays_unknown_without_losing_token(tmp_path: Path) -> None:
    raw = _raw_object()
    raw["type"] = "TYPE_FUTURE_UNKNOWN"
    label = _label(raw)
    output = tmp_path / "label.json"
    SourceLaserJsonExporter().export_frame(label, output)
    assert json.loads(output.read_text(encoding="utf-8"))[0]["type"] == raw["type"]


def test_new_objects_use_existing_uuid_canonical_type_and_metadata(tmp_path: Path) -> None:
    obj = LabeledObject(
        id="18bd7baf-58a7-4db1-b1ae-6b38c16d1090", class_name="Pedestrian",
        box3d=Box3D(1, 2, 0.9, 0.6, 0.6, 1.8, 0), attributes={"difficulty": "normal"},
        source={"created_by": "lidar_label_tool"},
    )
    label = replace(_label(), objects=(obj,))
    exporter = SourceLaserJsonExporter()
    output = tmp_path / "label.json"
    exporter.export_frame(label, output)
    raw = json.loads(output.read_text(encoding="utf-8"))[0]
    assert raw["id"] == obj.id
    assert raw["type"] == "TYPE_PEDESTRIAN"
    assert raw["metadata"] == obj.attributes
    assert exporter.describe(label).new_object_count == 1
    assert exporter.describe(label).omitted_object_fields == (f"{obj.id}.source.created_by",)


@pytest.mark.parametrize("mode", ["existing", "racing", "failure"])
def test_atomic_publish_never_overwrites_or_leaves_partial_file(tmp_path: Path, mode: str) -> None:
    output = tmp_path / "label.json"
    exporter = SourceLaserJsonExporter()
    real_link = os.link
    if mode == "existing":
        output.write_bytes(b"existing-source")
        with pytest.raises(FileExistsError):
            exporter.export_frame(_label(), output)
        assert output.read_bytes() == b"existing-source"
    else:
        def publish(source: Path, target: Path) -> None:
            if mode == "racing":
                target.write_bytes(b"other-writer")
                real_link(source, target)
            else:
                raise OSError("disk failure")

        with patch("lidar_label_tool.exporters.atomic_output.os.link", publish):
            with pytest.raises(OSError):
                exporter.export_frame(_label(), output)
        if mode == "racing":
            assert output.read_bytes() == b"other-writer"
        else:
            assert not output.exists()
    assert not tuple(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("metadata", [{"bad": float("nan")}, {"tuple": (1, 2)}, {1: "key"}])
def test_invalid_metadata_preflight_prevents_partial_batch(tmp_path: Path, metadata: dict) -> None:
    first = _label()
    second = replace(first, frame_id="000002", objects=(
        replace(first.objects[0], attributes=metadata),
    ))
    output = tmp_path / "batch"
    with pytest.raises(ValueError, match="not valid JSON"):
        export_frames((first, second), SourceLaserJsonExporter(), output)
    assert not output.exists()


@pytest.mark.parametrize("coordinate", [{"x": "right", "y": "forward", "z": "up"},
                                          {"unit": "centimeter"}, {}])
def test_noncanonical_coordinates_are_not_silently_converted(tmp_path: Path, coordinate: dict) -> None:
    output = tmp_path / "label.json"
    with pytest.raises(ValueError, match="canonical meter"):
        SourceLaserJsonExporter().export_frame(replace(_label(), coordinate_system=coordinate), output)
    assert not output.exists()


def test_empty_frame_exports_empty_array_and_v2_coordinates_are_supported(tmp_path: Path) -> None:
    coordinate = {
        "unit": "meter", "x_axis": "forward", "y_axis": "left", "z_axis": "up",
        "yaw_axis": "+z", "yaw_unit": "radian", "yaw_zero": "+x",
        "yaw_direction": "counterclockwise", "box_center": "geometric_center",
    }
    label = replace(_label(), objects=(), coordinate_system=coordinate)
    output = tmp_path / "empty.json"
    SourceLaserJsonExporter().export_frame(label, output)
    assert json.loads(output.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("raw", [[], {"box": []}, {"metadata": []}])
def test_malformed_source_raw_is_not_discarded(tmp_path: Path, raw: object) -> None:
    label = _label()
    obj = replace(label.objects[0], source={"format": "waymo_json", "raw": raw})
    with pytest.raises(ValueError, match="source"):
        SourceLaserJsonExporter().export_frame(replace(label, objects=(obj,)), tmp_path / "label.json")
    assert not tuple(tmp_path.iterdir())

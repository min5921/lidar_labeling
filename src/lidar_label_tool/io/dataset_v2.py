from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, cast

from lidar_label_tool.domain.dataset_v2 import (
    CameraMode,
    CameraSensorV2,
    CoordinateSystemV2,
    DataRootKind,
    DataRootV2,
    DatasetManifestV2,
    DatasetProfileV2,
    FrameCameraSampleV2,
    FrameIndexGenerationV2,
    FrameIndexRecordV2,
    FrameIndexReferenceV2,
    FrameLidarSampleV2,
    FrameMatchV2,
    LidarFormat,
    LidarSensorV2,
    MatchStatus,
    ProfileCameraV2,
    SyncMethod,
    TaxonomyClassV2,
    TaxonomyReferenceV2,
    TaxonomyV2,
    TimestampSpecV2,
)
from lidar_label_tool.io.json_schema import (
    JsonDocumentError,
    JsonSchemaValidationError,
    read_json_document,
    validate_json_document,
)


@dataclass(frozen=True, slots=True)
class DatasetManifestHeader:
    path: Path
    schema_version: str
    layout: str


def read_dataset_manifest_header(config_root: Path) -> DatasetManifestHeader:
    path = Path(config_root) / "dataset.json"
    document = read_json_document(path)
    if not isinstance(document, Mapping):
        raise JsonDocumentError(f"dataset manifest root must be an object: {path}")
    schema_version = document.get("schema_version")
    layout = document.get("layout")
    if not isinstance(schema_version, str) or not isinstance(layout, str):
        raise JsonDocumentError(
            f"dataset manifest requires string schema_version and layout: {path}"
        )
    return DatasetManifestHeader(
        path=path,
        schema_version=schema_version,
        layout=layout,
    )


def load_dataset_manifest_v2(
    config_root: Path,
    *,
    schema_root: Path | None = None,
) -> DatasetManifestV2:
    header = read_dataset_manifest_header(config_root)
    if header.schema_version != "2.0" or header.layout != "device_centric_v2":
        raise JsonDocumentError(
            "dataset manifest is not device-centric v2: "
            f"schema_version={header.schema_version!r}, layout={header.layout!r}"
        )
    document = read_json_document(header.path)
    return parse_dataset_manifest_v2(document, schema_root=schema_root)


def parse_dataset_manifest_v2(
    document: Any,
    *,
    schema_root: Path | None = None,
) -> DatasetManifestV2:
    """Validate and parse an in-memory v2 manifest document."""
    validate_json_document(document, "dataset-v2.schema.json", resource_root=schema_root)
    data = cast(dict[str, Any], document)
    coordinate = cast(dict[str, Any], data["coordinate_system"])
    root = cast(dict[str, Any], data["data_root"])
    camera_data = data["camera"]
    return DatasetManifestV2(
        dataset_id=str(data["dataset_id"]),
        display_name=str(data["display_name"]),
        manifest_revision=int(data["manifest_revision"]),
        data_root=DataRootV2(
            kind=cast(DataRootKind, str(root["kind"])),
            path=str(root["path"]),
        ),
        coordinate_system=CoordinateSystemV2(
            unit=str(coordinate["unit"]),
            x_axis=str(coordinate["x_axis"]),
            y_axis=str(coordinate["y_axis"]),
            z_axis=str(coordinate["z_axis"]),
            yaw_axis=str(coordinate["yaw_axis"]),
            yaw_unit=str(coordinate["yaw_unit"]),
            yaw_zero=str(coordinate["yaw_zero"]),
            yaw_direction=str(coordinate["yaw_direction"]),
            box_center=str(coordinate["box_center"]),
        ),
        lidars=tuple(_lidar_sensor(cast(dict[str, Any], item)) for item in data["lidars"]),
        camera=(
            _camera_sensor(cast(dict[str, Any], camera_data))
            if camera_data is not None
            else None
        ),
        profiles=tuple(
            _profile(cast(dict[str, Any], item)) for item in data["profiles"]
        ),
        default_profile_id=str(data["default_profile_id"]),
        taxonomy=_taxonomy_reference(cast(dict[str, Any], data["taxonomy"])),
        metadata=dict(cast(Mapping[str, Any], data.get("metadata", {}))),
    )


def load_frame_index_v2(
    path: Path,
    *,
    schema_root: Path | None = None,
) -> tuple[FrameIndexRecordV2, ...]:
    index_path = Path(path)
    try:
        text = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise JsonDocumentError(
            f"cannot read frame index {index_path}: {type(exc).__name__}: {exc}"
        ) from exc
    records: list[FrameIndexRecordV2] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
            validate_json_document(
                document,
                "frame-index-v2.schema.json",
                resource_root=schema_root,
            )
        except (json.JSONDecodeError, JsonSchemaValidationError) as exc:
            raise JsonDocumentError(
                f"invalid frame index record {index_path}:{line_number}: {exc}"
            ) from exc
        records.append(_frame_record(cast(dict[str, Any], document)))
    return tuple(records)


def load_taxonomy_v2(
    path: Path,
    *,
    schema_root: Path | None = None,
) -> TaxonomyV2:
    document = read_json_document(path)
    validate_json_document(document, "taxonomy.schema.json", resource_root=schema_root)
    data = cast(dict[str, Any], document)
    classes = []
    for value in data["classes"]:
        item = cast(dict[str, Any], value)
        size = cast(dict[str, Any], item["default_size_m"])
        classes.append(
            TaxonomyClassV2(
                id=str(item["id"]),
                display_name=str(item["display_name"]),
                color=str(item["color"]),
                length=float(size["length"]),
                width=float(size["width"]),
                height=float(size["height"]),
                shortcut=str(item["shortcut"]) if "shortcut" in item else None,
                aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            )
        )
    mappings = {
        str(namespace): {
            str(source): str(target)
            for source, target in cast(Mapping[str, Any], values).items()
        }
        for namespace, values in cast(
            Mapping[str, Any], data.get("source_mappings", {})
        ).items()
    }
    return TaxonomyV2(
        display_name=str(data["display_name"]),
        classes=tuple(classes),
        fallback_class_id=(
            str(data["fallback_class_id"]) if "fallback_class_id" in data else None
        ),
        source_mappings=mappings,
        metadata=dict(cast(Mapping[str, Any], data.get("metadata", {}))),
    )


def canonical_frame_index_bytes(records: tuple[FrameIndexRecordV2, ...]) -> bytes:
    text = "".join(
        json.dumps(
            record.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
        for record in records
    )
    return text.encode("utf-8")


def _timestamp_spec(value: object) -> TimestampSpecV2 | None:
    if value is None:
        return None
    data = cast(dict[str, Any], value)
    return TimestampSpecV2(
        path=str(data["path"]),
        sample_id_column=str(data["sample_id_column"]),
        value_column=str(data["value_column"]),
        unit=str(data["unit"]),
        clock_domain=str(data["clock_domain"]),
        offset_ns=int(data["offset_ns"]),
        sha256=str(data["sha256"]),
        format=str(data["format"]),
    )


def _lidar_sensor(data: dict[str, Any]) -> LidarSensorV2:
    return LidarSensorV2(
        id=str(data["id"]),
        display_name=str(data["display_name"]),
        coordinate_frame=str(data["coordinate_frame"]),
        format=cast(LidarFormat, str(data["format"])),
        data_pattern=str(data["data_pattern"]),
        point_columns=tuple(str(value) for value in data["point_columns"]),
        point_dtype=str(data["point_dtype"]) if "point_dtype" in data else None,
        byte_order=str(data["byte_order"]) if "byte_order" in data else None,
        timestamp=_timestamp_spec(data.get("timestamp")),
    )


def _camera_sensor(data: dict[str, Any]) -> CameraSensorV2:
    return CameraSensorV2(
        id=str(data["id"]),
        display_name=str(data["display_name"]),
        coordinate_frame=str(data["coordinate_frame"]),
        image_pattern=str(data["image_pattern"]),
        timestamp=_timestamp_spec(data.get("timestamp")),
    )


def _profile(data: dict[str, Any]) -> DatasetProfileV2:
    camera_data = data["camera"]
    frame_index = cast(dict[str, Any], data["frame_index"])
    generation = cast(dict[str, Any], frame_index["generation"])
    camera = None
    if camera_data is not None:
        value = cast(dict[str, Any], camera_data)
        camera = ProfileCameraV2(
            camera_id=str(value["camera_id"]),
            mode=cast(CameraMode, str(value["mode"])),
            calibration_path=(
                str(value["calibration_path"])
                if value["calibration_path"] is not None
                else None
            ),
            calibration_sha256=(
                str(value["calibration_sha256"])
                if value["calibration_sha256"] is not None
                else None
            ),
        )
    return DatasetProfileV2(
        id=str(data["id"]),
        display_name=str(data["display_name"]),
        lidar_id=str(data["lidar_id"]),
        camera=camera,
        frame_index=FrameIndexReferenceV2(
            path=str(frame_index["path"]),
            sha256=str(frame_index["sha256"]),
            frame_count=int(frame_index["frame_count"]),
            generation=FrameIndexGenerationV2(
                method=cast(SyncMethod, str(generation["method"])),
                tolerance_ns=(
                    int(generation["tolerance_ns"])
                    if generation.get("tolerance_ns") is not None
                    else None
                ),
            ),
            schema_version=str(frame_index["schema_version"]),
        ),
    )


def _taxonomy_reference(data: dict[str, Any]) -> TaxonomyReferenceV2:
    return TaxonomyReferenceV2(
        path=str(data["path"]),
        sha256=str(data["sha256"]),
        schema_version=str(data["schema_version"]),
    )


def _frame_record(data: dict[str, Any]) -> FrameIndexRecordV2:
    lidar = cast(dict[str, Any], data["lidar"])
    camera_data = data["camera"]
    match = cast(dict[str, Any], data["match"])
    camera = None
    if camera_data is not None:
        value = cast(dict[str, Any], camera_data)
        camera = FrameCameraSampleV2(
            sensor_id=str(value["sensor_id"]),
            sample_id=str(value["sample_id"]),
            source_sample_id=str(value["source_sample_id"]),
            path=str(value["path"]),
            timestamp_ns=(
                int(value["timestamp_ns"])
                if value["timestamp_ns"] is not None
                else None
            ),
            delta_ns=int(value["delta_ns"]) if value["delta_ns"] is not None else None,
        )
    return FrameIndexRecordV2(
        profile_id=str(data["profile_id"]),
        ordinal=int(data["ordinal"]),
        frame_id=str(data["frame_id"]),
        lidar=FrameLidarSampleV2(
            sensor_id=str(lidar["sensor_id"]),
            sample_id=str(lidar["sample_id"]),
            source_sample_id=str(lidar["source_sample_id"]),
            path=str(lidar["path"]),
            timestamp_ns=(
                int(lidar["timestamp_ns"])
                if lidar["timestamp_ns"] is not None
                else None
            ),
        ),
        camera=camera,
        match=FrameMatchV2(
            method=cast(SyncMethod, str(match["method"])),
            status=cast(MatchStatus, str(match["status"])),
            tolerance_ns=(
                int(match["tolerance_ns"])
                if match["tolerance_ns"] is not None
                else None
            ),
        ),
        schema_version=str(data["schema_version"]),
    )

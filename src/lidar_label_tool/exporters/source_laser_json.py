from __future__ import annotations

from collections.abc import Collection, Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel, LabeledObject
from lidar_label_tool.exporters.atomic_output import publish_new_export, require_new_export_path
from lidar_label_tool.exporters.validation import validate_label_for_export
from lidar_label_tool.io.labels.object_source import normalized_label_coordinates
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter


DEFAULT_SOURCE_CLASS_MAPPING = {
    "TYPE_VEHICLE": "Car",
    "TYPE_PEDESTRIAN": "Pedestrian",
    "TYPE_CYCLIST": "Cyclist",
    "TYPE_SIGN": "Sign",
    "TYPE_UNKNOWN": "Unknown",
}
_TOP_LEVEL_ATTRIBUTES = frozenset(
    {
        "num_lidar_points_in_box",
        "num_top_lidar_points_in_box",
        "detection_difficulty_level",
        "tracking_difficulty_level",
        "most_visible_camera_name",
    }
)
@dataclass(frozen=True, slots=True)
class SourceExportReport:
    frame_id: str
    object_count: int
    source_object_count: int
    new_object_count: int
    changed_id_object_ids: tuple[str, ...]
    changed_type_object_ids: tuple[str, ...]
    omitted_frame_fields: tuple[str, ...]
    omitted_object_fields: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceLaserJsonExporter:
    """Export the source laser_labels.json array, not a Waymo protobuf dataset.

    Boxes retain reference-frame meters, geometric centers and +z radian yaw.
    Only preserved object ``source.raw`` is used; no source path is opened or
    overwritten. Explicit class-to-source-type mappings resolve ambiguous reverse
    mappings. Current IDs include deliberate user links; the report identifies
    differences from preserved source IDs.
    """

    name = "source_laser_json"
    extension = ".json"

    def __init__(
        self,
        allowed_classes: Collection[str] | None = None,
        *,
        source_class_mapping: Mapping[str, str] | None = None,
        export_class_mapping: Mapping[str, str] | None = None,
    ) -> None:
        self.allowed_classes = tuple(allowed_classes) if allowed_classes is not None else None
        self.source_class_mapping = dict(
            DEFAULT_SOURCE_CLASS_MAPPING if source_class_mapping is None else source_class_mapping
        )
        self.export_class_mapping = dict(export_class_mapping or {})
        for mapping in (self.source_class_mapping, self.export_class_mapping):
            if any(
                not isinstance(key, str) or not key.strip()
                or not isinstance(value, str) or not value.strip()
                for key, value in mapping.items()
            ):
                raise ValueError("source export class mappings require non-empty strings")

    def validate(self, label: FrameLabel) -> None:
        self._build(label)

    def describe(self, label: FrameLabel) -> SourceExportReport:
        """Validate and describe metadata loss before the caller starts an export."""
        return self._build(label)[1]

    def _source_type(self, obj: LabeledObject, raw: Mapping[str, Any]) -> str:
        explicit = self.export_class_mapping.get(obj.class_name)
        if explicit is not None:
            return explicit
        source_type = raw.get("type", obj.source.get("type"))
        if isinstance(source_type, str) and source_type:
            # The importer retains unrecognized source types as Unknown. Keeping
            # the original token is lossless, unlike changing it to TYPE_UNKNOWN.
            source_class = self.source_class_mapping.get(source_type, "Unknown")
            if source_class == obj.class_name:
                return source_type
        candidates = sorted(
            source_type for source_type, class_name in self.source_class_mapping.items()
            if class_name == obj.class_name
        )
        if len(candidates) != 1:
            reason = "ambiguous" if candidates else "unmapped"
            raise ValueError(
                f"{reason} source class mapping for {obj.class_name!r} (object {obj.id!r}); "
                "provide an explicit export class-to-source-type mapping"
            )
        return candidates[0]

    def _object_document(self, obj: LabeledObject) -> dict[str, Any]:
        raw = obj.source.get("raw")
        if raw is not None and (
            not isinstance(raw, Mapping)
            or obj.source.get("format") not in {
                "waymo_json", "waymo_frame_json", "device_centric_json"
            }
        ):
            raise ValueError(f"object {obj.id!r} has unsupported source.raw metadata")
        document: dict[str, Any] = deepcopy(dict(raw)) if raw is not None else {}
        raw_box = document.get("box", {})
        raw_metadata = document.get("metadata", {})
        if not isinstance(raw_box, Mapping) or not isinstance(raw_metadata, Mapping):
            raise ValueError(f"object {obj.id!r} source box/metadata must be objects")
        document["type"] = self._source_type(obj, document)
        document["id"] = obj.id
        box = deepcopy(dict(raw_box))
        box.update(
            center_x=obj.box3d.x, center_y=obj.box3d.y, center_z=obj.box3d.z,
            length=obj.box3d.length, width=obj.box3d.width, height=obj.box3d.height,
            heading=obj.box3d.yaw,
        )
        document["box"] = box
        # The importer promotes these five fields over equally-named metadata.
        # Keep shadowed raw metadata verbatim while editing the promoted value.
        metadata = {
            key: deepcopy(value) for key, value in raw_metadata.items()
            if key in _TOP_LEVEL_ATTRIBUTES
        }
        metadata.update(
            (key, deepcopy(value)) for key, value in obj.attributes.items()
            if key not in _TOP_LEVEL_ATTRIBUTES
        )
        if metadata or "metadata" in document:
            document["metadata"] = metadata
        for key in _TOP_LEVEL_ATTRIBUTES:
            if key in obj.attributes:
                document[key] = deepcopy(obj.attributes[key])
            else:
                document.pop(key, None)
                metadata.pop(key, None)
        restored = WaymoLabelImporter({document["type"]: obj.class_name}).import_laser_objects(
            (document,)
        )[0]
        if (
            restored.id != obj.id or restored.box3d != obj.box3d
            or restored.class_name != obj.class_name or restored.attributes != obj.attributes
        ):
            raise ValueError(f"object {obj.id!r} source export failed round-trip validation")
        return document

    def _build(self, label: FrameLabel) -> tuple[list[dict[str, Any]], SourceExportReport]:
        validate_label_for_export(label, allowed_classes=self.allowed_classes)
        try:
            normalized_label_coordinates(label.coordinate_system)
        except ValueError as exc:
            raise ValueError(
                "source export requires canonical meter/center/+z-radian coordinates"
            ) from exc
        documents = [self._object_document(obj) for obj in label.objects]
        # Reject non-JSON unknown fields or non-finite metadata during preflight,
        # before batch export has written any earlier frames.
        try:
            serialized = json.dumps(documents, ensure_ascii=False, allow_nan=False)
            if json.loads(serialized) != documents:
                raise ValueError("metadata requires lossy JSON type conversion")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"source export metadata is not valid JSON: {exc}") from exc
        changed_ids: list[str] = []
        changed_types: list[str] = []
        omitted: list[str] = []
        source_count = 0
        for obj, document in zip(label.objects, documents, strict=True):
            raw = obj.source.get("raw")
            if isinstance(raw, Mapping):
                source_count += 1
                if raw.get("id") != obj.id:
                    changed_ids.append(obj.id)
                if raw.get("type") != document["type"]:
                    changed_types.append(obj.id)
            omitted.extend(f"{obj.id}.{key}" for key in sorted(obj.extra_fields))
            omitted.extend(
                f"{obj.id}.source.{key}" for key in sorted(obj.source)
                if key not in {"raw", "format", "type"}
            )
        frame_fields = tuple(sorted(key for key in label.to_dict() if key != "objects"))
        warnings = [
            "원본 호환 배열은 frame identity·revision·검토 상태·provenance를 담지 않습니다. "
            "작업 JSON과 export 보고서를 함께 보관하세요.",
            "박스는 현재 reference frame의 meter/기하 중심/+z radian이며 좌표 변환하지 않습니다. "
            "Waymo 공식 protobuf 또는 학습 데이터셋 전체 export가 아닙니다.",
        ]
        if omitted:
            warnings.append("원본 형식에 위치가 없는 작업 전용 객체 metadata가 생략됩니다.")
        if changed_ids:
            warnings.append("연결된 현재 객체 ID 또는 문자열 정규화 ID가 원본 raw ID를 대신합니다.")
        if changed_types:
            warnings.append("변경된 class 또는 명시 mapping에 따라 원본 type이 변경됩니다.")
        if source_count:
            warnings.append(
                "원본 velocity·point count 등 metadata는 편집 박스에 맞춰 재계산하지 않습니다."
            )
        return documents, SourceExportReport(
            frame_id=label.frame_id, object_count=len(documents),
            source_object_count=source_count, new_object_count=len(documents) - source_count,
            changed_id_object_ids=tuple(changed_ids), changed_type_object_ids=tuple(changed_types),
            omitted_frame_fields=frame_fields, omitted_object_fields=tuple(omitted),
            warnings=tuple(warnings),
        )

    def export_frame(self, label: FrameLabel, output_path: Path) -> None:
        documents, _ = self._build(label)
        target = Path(output_path)
        require_new_export_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(documents, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            with temporary.open("r", encoding="utf-8") as stream:
                if json.load(stream) != documents:
                    raise ValueError("source export JSON failed round-trip validation")
            publish_new_export(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

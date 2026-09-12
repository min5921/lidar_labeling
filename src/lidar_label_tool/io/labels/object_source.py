from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.json_schema import validate_json_document


CANONICAL_COORDINATES = {
    "unit": "meter",
    "x_axis": "forward",
    "y_axis": "left",
    "z_axis": "up",
    "yaw_axis": "+z",
    "yaw_unit": "radian",
    "yaw_zero": "+x",
    "yaw_direction": "counterclockwise",
    "box_center": "geometric_center",
}


def normalized_label_coordinates(coordinates: Mapping[str, str]) -> dict[str, str]:
    """Expand the documented v1 coordinate contract, or validate the v2 contract."""
    if dict(coordinates) == {"x": "forward", "y": "left", "z": "up"}:
        return dict(CANONICAL_COORDINATES)
    if dict(coordinates) != CANONICAL_COORDINATES:
        raise ValueError("지원되는 meter / x-forward / y-left / z-up 박스 좌표계가 아닙니다.")
    return dict(coordinates)


@dataclass(frozen=True, slots=True)
class SavedObjectSource:
    path: Path
    sha256: str
    schema_version: str
    dataset_id: str
    profile_id: str | None
    frame_id: str
    reference_frame: str
    lidar_ids: tuple[str, ...]
    coordinate_system: Mapping[str, str]
    objects: tuple[LabeledObject, ...]


class SavedLabelObjectLoader:
    """Read objects from a saved label without following any embedded data paths."""

    def load(self, path: Path) -> SavedObjectSource:
        path = Path(path).resolve()
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(document, dict):
            raise ValueError("저장된 작업 라벨 JSON을 선택하세요.")
        version = document.get("schema_version")
        if not isinstance(version, str) or version not in {"1.0", "2.0"}:
            raise ValueError("지원하는 작업 라벨 버전은 1.0과 2.0입니다.")
        schema = "label-v2.schema.json" if version == "2.0" else "label.schema.json"
        validate_json_document(document, schema)
        if any(not isinstance(item.get("source", {}), dict) for item in document["objects"]):
            raise ValueError("객체 source metadata는 JSON object여야 합니다.")
        if version == "1.0":
            label = FrameLabel.from_dict(document)
            objects = label.objects
            lidar_ids = tuple(sorted(label.point_cloud_paths))
            profile_id = None
        else:
            known = {"id", "class_id", "box3d", "attributes", "source"}
            objects = tuple(
                LabeledObject(
                    id=item["id"], class_name=item["class_id"],
                    box3d=Box3D.from_dict(item["box3d"]),
                    attributes=dict(item.get("attributes", {})),
                    source=dict(item.get("source", {})),
                    extra_fields={key: value for key, value in item.items() if key not in known},
                )
                for item in document["objects"]
            )
            lidar_ids = (document["label_lidar_id"],)
            profile_id = document["profile_id"]
        if len({obj.id for obj in objects}) != len(objects):
            raise ValueError("이전 작업 라벨에 중복 객체 ID가 있습니다.")
        return SavedObjectSource(
            path=path, sha256=hashlib.sha256(raw).hexdigest(), schema_version=version,
            dataset_id=document["dataset_id"], profile_id=profile_id,
            frame_id=document["frame_id"], reference_frame=document["reference_frame"],
            lidar_ids=lidar_ids,
            coordinate_system=normalized_label_coordinates(document["coordinate_system"]),
            objects=objects,
        )

    @staticmethod
    def require_unchanged(source: SavedObjectSource) -> None:
        if hashlib.sha256(source.path.read_bytes()).hexdigest() != source.sha256:
            raise ValueError("미리보기 이후 이전 작업 라벨이 변경되었습니다. 다시 선택하세요.")

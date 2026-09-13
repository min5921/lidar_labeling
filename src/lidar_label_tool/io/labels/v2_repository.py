from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Mapping
from uuid import uuid4

from lidar_label_tool.domain.dataset_v2 import FrameIndexRecordV2
from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject, utc_now_iso
from lidar_label_tool.domain.label_identity_v2 import (
    frame_record_sha256,
    lidar_binding_sha256,
)
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.json_schema import (
    JsonDocumentError,
    read_json_document,
    validate_json_document,
)
from lidar_label_tool.io.labels.json_repository import LabelConflictError


_V2_LABEL_FIELDS = {
    "schema_version",
    "dataset_id",
    "profile_id",
    "label_lidar_id",
    "frame_id",
    "label_lidar_sample_id",
    "revision",
    "frame_status",
    "saved_at_utc",
    "point_cloud_path",
    "image_path",
    "reference_frame",
    "coordinate_system",
    "provenance",
    "calibration_state",
    "objects",
}
_V2_OBJECT_FIELDS = {"id", "class_id", "box3d", "attributes", "source"}


class V2LabelIdentityError(ValueError):
    pass


class V2LabelRepository:
    """Profile/LiDAR-scoped, atomic repository for v2 working labels."""

    def __init__(self, annotation_dir: Path, adapter: DeviceCentricV2Adapter) -> None:
        self.annotation_dir = Path(annotation_dir)
        self.adapter = adapter
        self.dataset_id = adapter.manifest.dataset_id
        self.profile_id = adapter.profile.id
        self.label_lidar_id = adapter.active_lidar.id
        self.reference_frame = adapter.active_lidar.coordinate_frame
        self._loaded_fingerprints: dict[str, str] = {}

    @classmethod
    def for_sidecar(cls, adapter: DeviceCentricV2Adapter) -> V2LabelRepository:
        return cls(
            adapter.configuration_root
            / "annotations"
            / "lidar_label_tool"
            / adapter.profile.id
            / adapter.active_lidar.id,
            adapter,
        )

    @classmethod
    def for_workspace(
        cls,
        workspace_root: Path,
        adapter: DeviceCentricV2Adapter,
    ) -> V2LabelRepository:
        return cls(
            Path(workspace_root)
            / adapter.manifest.dataset_id
            / "annotations"
            / "lidar_label_tool"
            / adapter.profile.id
            / adapter.active_lidar.id,
            adapter,
        )

    def path_for(self, frame_id: str) -> Path:
        record = self.adapter.frame_record(frame_id)
        if record.frame_id != frame_id:
            raise V2LabelIdentityError("frame ID does not match frozen frame index")
        return self.annotation_dir / f"{frame_id}.json"

    def exists(self, frame_id: str) -> bool:
        return self.path_for(frame_id).is_file()

    def load(self, frame_id: str) -> FrameLabel:
        label, fingerprint = self._read_label(frame_id)
        self._loaded_fingerprints[frame_id] = fingerprint
        return label

    def _read_label(self, frame_id: str) -> tuple[FrameLabel, str]:
        path = self.path_for(frame_id)
        try:
            payload = path.read_bytes()
            document = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise JsonDocumentError(
                f"cannot read JSON document {path}: {type(exc).__name__}: {exc}"
            ) from exc
        validate_json_document(document, "label-v2.schema.json")
        if not isinstance(document, Mapping):
            raise JsonDocumentError(f"v2 label root must be an object: {path}")
        self._require_identity(document, self.adapter.frame_record(frame_id), path=path)
        return self._frame_label(document), hashlib.sha256(payload).hexdigest()

    def load_backup(self, frame_id: str) -> FrameLabel:
        path = self.path_for(frame_id).with_suffix(".json.bak")
        document = read_json_document(path)
        validate_json_document(document, "label-v2.schema.json")
        if not isinstance(document, Mapping):
            raise JsonDocumentError(f"v2 backup root must be an object: {path}")
        self._require_identity(document, self.adapter.frame_record(frame_id), path=path)
        return self._frame_label(document)

    def save(self, label: FrameLabel) -> FrameLabel:
        self._require_frame_label_identity(label)
        target = self.path_for(label.frame_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        disk_revision = 0
        initial_fingerprint: str | None = None
        if target.exists():
            disk_label, initial_fingerprint = self._read_label(label.frame_id)
            disk_revision = disk_label.revision
            expected_fingerprint = self._loaded_fingerprints.get(label.frame_id)
            if expected_fingerprint != initial_fingerprint:
                raise LabelConflictError(
                    "working label changed since load; reload before saving"
                )
        if disk_revision != label.revision:
            raise LabelConflictError(
                f"working label changed on disk: expected revision {label.revision}, "
                f"found {disk_revision}"
            )

        revision = disk_revision + 1
        saved_at = utc_now_iso()
        payload = self.document_for(label, revision=revision, saved_at_utc=saved_at)
        token = uuid4().hex
        temporary = target.with_name(f".{target.name}.{token}.tmp")
        backup_temporary = target.with_name(f".{target.name}.{token}.bak.tmp")
        backup = target.with_suffix(".json.bak")
        try:
            _write_json_exclusive(temporary, payload)
            self._validate_written_document(temporary, label.frame_id, revision)
            saved_fingerprint = _sha256(temporary)
            if target.exists():
                if initial_fingerprint is None or _sha256(target) != initial_fingerprint:
                    raise LabelConflictError("working label changed during save")
                shutil.copy2(target, backup_temporary)
                if _sha256(backup_temporary) != initial_fingerprint:
                    raise LabelConflictError("working label changed while making backup")
                self._validate_written_document(
                    backup_temporary,
                    label.frame_id,
                    disk_revision,
                )
                os.replace(backup_temporary, backup)
            elif initial_fingerprint is not None:
                raise LabelConflictError("working label was removed during save")
            os.replace(temporary, target)
            self._loaded_fingerprints[label.frame_id] = saved_fingerprint
        finally:
            for path in (temporary, backup_temporary):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        return replace(
            label,
            revision=revision,
            saved_at_utc=saved_at,
            provenance=dict(payload["provenance"]),
            calibration_state=dict(payload["calibration_state"]),
        )

    def document_for(
        self,
        label: FrameLabel,
        *,
        revision: int,
        saved_at_utc: str,
    ) -> dict[str, Any]:
        self._require_frame_label_identity(label)
        record = self.adapter.frame_record(label.frame_id)
        point_path = _data_path(self.adapter.data_root, record.lidar.path)
        if not point_path.is_file():
            raise V2LabelIdentityError(f"active point cloud is missing: {point_path}")
        image_path: str | None = None
        image_sha256: str | None = None
        if record.camera is not None:
            candidate = _data_path(self.adapter.data_root, record.camera.path)
            if candidate.is_file():
                image_path = record.camera.path
                image_sha256 = _sha256(candidate)
        taxonomy_path = _config_path(
            self.adapter.configuration_root,
            self.adapter.manifest.taxonomy.path,
        )
        index_path = _config_path(
            self.adapter.configuration_root,
            self.adapter.profile.frame_index.path,
        )
        coordinate = self.adapter.manifest.coordinate_system
        result: dict[str, Any] = {
            key: value
            for key, value in label.extra_fields.items()
            if key not in _V2_LABEL_FIELDS
        }
        result.update(
            {
                "schema_version": "2.0",
                "dataset_id": self.dataset_id,
                "profile_id": self.profile_id,
                "label_lidar_id": self.label_lidar_id,
                "frame_id": record.frame_id,
                "label_lidar_sample_id": record.lidar.sample_id,
                "revision": revision,
                "frame_status": label.frame_status,
                "saved_at_utc": saved_at_utc,
                "point_cloud_path": record.lidar.path,
                "image_path": image_path,
                "reference_frame": self.reference_frame,
                "coordinate_system": {
                    "unit": coordinate.unit,
                    "x_axis": coordinate.x_axis,
                    "y_axis": coordinate.y_axis,
                    "z_axis": coordinate.z_axis,
                    "yaw_axis": coordinate.yaw_axis,
                    "yaw_unit": coordinate.yaw_unit,
                    "yaw_zero": coordinate.yaw_zero,
                    "yaw_direction": coordinate.yaw_direction,
                    "box_center": coordinate.box_center,
                },
                "provenance": {
                    **deepcopy(dict(label.provenance)),
                    "source_format": "device_centric_v2",
                    "source_paths": [],
                    "source_fingerprints": {},
                    "dataset_manifest": {
                        "path": "dataset.json",
                        "sha256": self.adapter.manifest_sha256,
                    },
                    "profile_sha256": self.adapter.profile_sha256,
                    "frame_index": {
                        "path": self.adapter.profile.frame_index.path,
                        "sha256": _sha256(index_path),
                        "lidar_binding_sha256": lidar_binding_sha256(record),
                        "frame_record_sha256": frame_record_sha256(record),
                    },
                    "taxonomy": {
                        "path": self.adapter.manifest.taxonomy.path,
                        "sha256": _sha256(taxonomy_path),
                    },
                    "point_cloud_sha256": _sha256(point_path),
                    "image_sha256": image_sha256,
                },
                "calibration_state": self._calibration_state(),
                "objects": [self._object_document(obj) for obj in label.objects],
            }
        )
        validate_json_document(result, "label-v2.schema.json")
        return result

    def base_label_sha256(self, frame_id: str) -> str | None:
        path = self.path_for(frame_id)
        return _sha256(path) if path.is_file() else None

    def frame_label_from_document(self, document: Mapping[str, Any]) -> FrameLabel:
        frame_id = str(document.get("frame_id", ""))
        self._require_identity(
            document,
            self.adapter.frame_record(frame_id),
            path=self.path_for(frame_id),
        )
        return self._frame_label(document)

    def _validate_written_document(
        self,
        path: Path,
        frame_id: str,
        expected_revision: int,
    ) -> None:
        document = read_json_document(path)
        validate_json_document(document, "label-v2.schema.json")
        if not isinstance(document, Mapping):
            raise JsonDocumentError(f"v2 label root must be an object: {path}")
        self._require_identity(document, self.adapter.frame_record(frame_id), path=path)
        if int(document["revision"]) != expected_revision:
            raise V2LabelIdentityError("temporary label revision validation failed")

    def _require_frame_label_identity(self, label: FrameLabel) -> None:
        if label.dataset_id != self.dataset_id:
            raise V2LabelIdentityError("label dataset_id does not match repository")
        record = self.adapter.frame_record(label.frame_id)
        if label.reference_frame != self.reference_frame:
            raise V2LabelIdentityError("label reference frame does not match active LiDAR")
        expected_paths = {self.label_lidar_id: (record.lidar.path,)}
        if dict(label.point_cloud_paths) != expected_paths:
            raise V2LabelIdentityError("label point binding does not match frozen LiDAR frame")
        class_ids = {item.id for item in self.adapter.taxonomy.classes}
        for obj in label.objects:
            if obj.class_name not in class_ids:
                raise V2LabelIdentityError(
                    f"object {obj.id!r} uses unknown taxonomy class {obj.class_name!r}"
                )

    def _require_identity(
        self,
        document: Mapping[str, Any],
        record: FrameIndexRecordV2,
        *,
        path: Path,
    ) -> None:
        expected = {
            "dataset_id": self.dataset_id,
            "profile_id": self.profile_id,
            "label_lidar_id": self.label_lidar_id,
            "frame_id": record.frame_id,
            "label_lidar_sample_id": record.lidar.sample_id,
            "reference_frame": self.reference_frame,
            "point_cloud_path": record.lidar.path,
        }
        for key, value in expected.items():
            if document.get(key) != value:
                raise V2LabelIdentityError(
                    f"v2 label identity mismatch for {key}: {path}"
                )
        provenance = document.get("provenance")
        if not isinstance(provenance, Mapping):
            raise V2LabelIdentityError(f"v2 label provenance is invalid: {path}")
        if provenance.get("profile_sha256") != self.adapter.profile_sha256:
            raise V2LabelIdentityError(f"v2 label profile identity changed: {path}")
        frame_index = provenance.get("frame_index")
        if not isinstance(frame_index, Mapping):
            raise V2LabelIdentityError(f"v2 label frame index provenance is invalid: {path}")
        if frame_index.get("lidar_binding_sha256") != lidar_binding_sha256(record):
            raise V2LabelIdentityError(f"v2 label LiDAR binding changed: {path}")
        current_point = _data_path(self.adapter.data_root, record.lidar.path)
        if not current_point.is_file():
            raise V2LabelIdentityError(f"v2 label point cloud is missing: {current_point}")
        if provenance.get("point_cloud_sha256") != _sha256(current_point):
            raise V2LabelIdentityError(f"v2 label point cloud changed: {path}")
        coordinate = document.get("coordinate_system")
        expected_coordinate = self.document_coordinate_system()
        if coordinate != expected_coordinate:
            raise V2LabelIdentityError(f"v2 label coordinate system changed: {path}")
        class_ids = {item.id for item in self.adapter.taxonomy.classes}
        object_ids: set[str] = set()
        for item in document.get("objects", []):
            object_id = str(item["id"])
            if object_id in object_ids:
                raise V2LabelIdentityError(f"duplicate v2 object ID: {object_id}")
            object_ids.add(object_id)
            if str(item["class_id"]) not in class_ids:
                raise V2LabelIdentityError(
                    f"v2 label uses unknown taxonomy class: {item['class_id']}"
                )

    def document_coordinate_system(self) -> dict[str, str]:
        coordinate = self.adapter.manifest.coordinate_system
        return {
            "unit": coordinate.unit,
            "x_axis": coordinate.x_axis,
            "y_axis": coordinate.y_axis,
            "z_axis": coordinate.z_axis,
            "yaw_axis": coordinate.yaw_axis,
            "yaw_unit": coordinate.yaw_unit,
            "yaw_zero": coordinate.yaw_zero,
            "yaw_direction": coordinate.yaw_direction,
            "box_center": coordinate.box_center,
        }

    def _frame_label(self, document: Mapping[str, Any]) -> FrameLabel:
        point_path = str(document["point_cloud_path"])
        image_path = document.get("image_path")
        return FrameLabel(
            dataset_id=str(document["dataset_id"]),
            frame_id=str(document["frame_id"]),
            point_cloud_paths={self.label_lidar_id: (point_path,)},
            image_paths=(
                {self.adapter.profile.camera.camera_id: str(image_path)}
                if image_path is not None and self.adapter.profile.camera is not None
                else {}
            ),
            reference_frame=str(document["reference_frame"]),
            objects=tuple(self._labeled_object(item) for item in document.get("objects", [])),
            revision=int(document["revision"]),
            frame_status=str(document["frame_status"]),
            saved_at_utc=str(document["saved_at_utc"]),
            provenance=dict(document["provenance"]),
            calibration_state=dict(document["calibration_state"]),
            coordinate_system=dict(document["coordinate_system"]),
            extra_fields={
                str(key): value
                for key, value in document.items()
                if key not in _V2_LABEL_FIELDS
            },
        )

    @staticmethod
    def _labeled_object(document: Mapping[str, Any]) -> LabeledObject:
        return LabeledObject(
            id=str(document["id"]),
            class_name=str(document["class_id"]),
            box3d=Box3D.from_dict(document["box3d"]),
            attributes=dict(document.get("attributes", {})),
            source=dict(document.get("source", {})),
            extra_fields={
                str(key): value
                for key, value in document.items()
                if key not in _V2_OBJECT_FIELDS
            },
        )

    @staticmethod
    def _object_document(obj: LabeledObject) -> dict[str, Any]:
        result = {
            key: value
            for key, value in obj.extra_fields.items()
            if key not in _V2_OBJECT_FIELDS
        }
        result.update(
            {
                "id": obj.id,
                "class_id": obj.class_name,
                "box3d": obj.box3d.to_dict(),
                "attributes": dict(obj.attributes),
            }
        )
        if obj.source:
            result["source"] = dict(obj.source)
        return result

    def _calibration_state(self) -> dict[str, Any]:
        return self.adapter.current_calibration_state()


def _write_json_exclusive(path: Path, document: Mapping[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _config_path(root: Path, relative: str) -> Path:
    return _safe_relative_path(root, relative, label="configuration")


def _data_path(root: Path, relative: str) -> Path:
    return _safe_relative_path(root, relative, label="data")


def _safe_relative_path(root: Path, relative: str, *, label: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise V2LabelIdentityError(f"unsafe {label} path: {relative}")
    candidate = root.joinpath(*pure.parts).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise V2LabelIdentityError(f"{label} path escapes root: {relative}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel, utc_now_iso
from lidar_label_tool.io.json_schema import (
    JsonDocumentError,
    read_json_document,
    validate_json_document,
)
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.recovery import RecoveryReadResult, RecoverySnapshotError


@dataclass(frozen=True, slots=True)
class V2RecoverySnapshot:
    dataset_id: str
    profile_id: str
    label_lidar_id: str
    frame_id: str
    reference_frame: str
    profile_sha256: str
    base_revision: int
    base_label_sha256: str | None
    created_at_utc: str
    label: FrameLabel


class V2RecoveryStore:
    """Recovery snapshots with the same profile/LiDAR identity as v2 labels."""

    def __init__(self, repository: V2LabelRepository) -> None:
        self.repository = repository
        self.recovery_dir = repository.annotation_dir / ".recovery"

    def path_for(self, frame_id: str) -> Path:
        self.repository.adapter.frame_record(frame_id)
        return self.recovery_dir / f"{frame_id}.recovery.json"

    def write(
        self,
        label: FrameLabel,
        *,
        base_revision: int,
        working_label_path: Path | None,
        tool_version: str,
    ) -> V2RecoverySnapshot:
        del working_label_path, tool_version
        created_at = utc_now_iso()
        embedded = self.repository.document_for(
            label,
            revision=max(1, base_revision),
            saved_at_utc=created_at,
        )
        document = {
            "schema_version": "2.0",
            "kind": "label_recovery",
            "dataset_id": self.repository.dataset_id,
            "profile_id": self.repository.profile_id,
            "label_lidar_id": self.repository.label_lidar_id,
            "frame_id": label.frame_id,
            "reference_frame": self.repository.reference_frame,
            "profile_sha256": self.repository.adapter.profile_sha256,
            "base_revision": base_revision,
            "base_label_sha256": self.repository.base_label_sha256(label.frame_id),
            "created_at_utc": created_at,
            "label": embedded,
        }
        validate_json_document(document, "recovery-v2.schema.json")
        target = self.path_for(label.frame_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            snapshot = self._snapshot(read_json_document(temporary), path=temporary)
            os.replace(temporary, target)
            return snapshot
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def load(self, frame_id: str) -> V2RecoverySnapshot:
        path = self.path_for(frame_id)
        return self._snapshot(read_json_document(path), path=path)

    def inspect(self, frame_id: str) -> RecoveryReadResult:
        path = self.path_for(frame_id)
        if not path.is_file():
            return RecoveryReadResult(None)
        try:
            snapshot = self.load(frame_id)
        except (OSError, ValueError, JsonDocumentError) as exc:
            return RecoveryReadResult(None, str(exc))
        return RecoveryReadResult(snapshot)

    def is_newer_than_working(self, frame_id: str, working_label_path: Path) -> bool:
        recovery_path = self.path_for(frame_id)
        if not recovery_path.is_file():
            return False
        working = Path(working_label_path)
        if not working.is_file():
            return True
        return recovery_path.stat().st_mtime_ns > working.stat().st_mtime_ns

    def delete(self, frame_id: str) -> bool:
        try:
            self.path_for(frame_id).unlink()
        except FileNotFoundError:
            return False
        return True

    def _snapshot(self, document: Any, *, path: Path) -> V2RecoverySnapshot:
        if not isinstance(document, Mapping):
            raise RecoverySnapshotError(f"recovery root must be an object: {path}")
        validate_json_document(document, "recovery-v2.schema.json")
        expected = {
            "dataset_id": self.repository.dataset_id,
            "profile_id": self.repository.profile_id,
            "label_lidar_id": self.repository.label_lidar_id,
            "reference_frame": self.repository.reference_frame,
            "profile_sha256": self.repository.adapter.profile_sha256,
        }
        for key, value in expected.items():
            if document.get(key) != value:
                raise RecoverySnapshotError(f"v2 recovery identity mismatch: {key}")
        embedded = document["label"]
        if not isinstance(embedded, Mapping):
            raise RecoverySnapshotError("v2 recovery embedded label is invalid")
        validate_json_document(embedded, "label-v2.schema.json")
        for key in (
            "dataset_id",
            "profile_id",
            "label_lidar_id",
            "frame_id",
            "reference_frame",
        ):
            if embedded.get(key) != document.get(key):
                raise RecoverySnapshotError(
                    f"v2 recovery embedded label identity mismatch: {key}"
                )
        base_revision = int(document["base_revision"])
        current_base = self.repository.base_label_sha256(str(document["frame_id"]))
        if document.get("base_label_sha256") != current_base:
            raise RecoverySnapshotError(
                "v2 recovery base label fingerprint no longer matches working label"
            )
        label = replace(
            self.repository.frame_label_from_document(embedded),
            revision=base_revision,
        )
        return V2RecoverySnapshot(
            dataset_id=str(document["dataset_id"]),
            profile_id=str(document["profile_id"]),
            label_lidar_id=str(document["label_lidar_id"]),
            frame_id=str(document["frame_id"]),
            reference_frame=str(document["reference_frame"]),
            profile_sha256=str(document["profile_sha256"]),
            base_revision=base_revision,
            base_label_sha256=(
                str(document["base_label_sha256"])
                if document.get("base_label_sha256") is not None
                else None
            ),
            created_at_utc=str(document["created_at_utc"]),
            label=label,
        )

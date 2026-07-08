from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel, utc_now_iso


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class RecoverySnapshotError(ValueError):
    """Raised when a recovery file cannot be validated."""


@dataclass(frozen=True, slots=True)
class RecoverySnapshot:
    dataset_id: str
    frame_id: str
    base_revision: int
    created_at_utc: str
    label: FrameLabel
    working_label_path: str | None
    tool_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "dataset_id": self.dataset_id,
            "frame_id": self.frame_id,
            "base_revision": self.base_revision,
            "created_at_utc": self.created_at_utc,
            "working_label_path": self.working_label_path,
            "tool_version": self.tool_version,
            "label": self.label.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RecoverySnapshot:
        try:
            label = FrameLabel.from_dict(data["label"])
            snapshot = cls(
                dataset_id=str(data["dataset_id"]),
                frame_id=str(data["frame_id"]),
                base_revision=int(data["base_revision"]),
                created_at_utc=str(data["created_at_utc"]),
                label=label,
                working_label_path=(
                    str(data["working_label_path"])
                    if data.get("working_label_path") is not None
                    else None
                ),
                tool_version=str(data.get("tool_version", "unknown")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RecoverySnapshotError(f"invalid recovery snapshot: {exc}") from exc
        if snapshot.base_revision < 0:
            raise RecoverySnapshotError("base_revision must be non-negative")
        if label.dataset_id != snapshot.dataset_id or label.frame_id != snapshot.frame_id:
            raise RecoverySnapshotError("recovery label identity mismatch")
        return snapshot


@dataclass(frozen=True, slots=True)
class RecoveryReadResult:
    snapshot: RecoverySnapshot | None
    error: str | None = None


class RecoveryStore:
    """Atomic storage for unsaved labels, separate from normal working labels."""

    def __init__(self, annotation_dir: Path) -> None:
        self.recovery_dir = Path(annotation_dir) / ".recovery"

    def path_for(self, frame_id: str) -> Path:
        if (
            not frame_id
            or not _SAFE_COMPONENT.fullmatch(frame_id)
            or frame_id in {".", ".."}
        ):
            raise ValueError("frame_id contains unsupported path characters")
        return self.recovery_dir / f"{frame_id}.recovery.json"

    def write(
        self,
        label: FrameLabel,
        *,
        base_revision: int,
        working_label_path: Path | None,
        tool_version: str,
    ) -> RecoverySnapshot:
        canonical_label = FrameLabel.from_dict(label.to_dict())
        snapshot = RecoverySnapshot(
            dataset_id=canonical_label.dataset_id,
            frame_id=canonical_label.frame_id,
            base_revision=base_revision,
            created_at_utc=utc_now_iso(),
            label=canonical_label,
            working_label_path=str(working_label_path) if working_label_path else None,
            tool_version=tool_version,
        )
        target = self.path_for(label.frame_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        validated_snapshot = snapshot
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(snapshot.to_dict(), stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            with temporary.open("r", encoding="utf-8") as stream:
                validated_snapshot = RecoverySnapshot.from_dict(json.load(stream))
            os.replace(temporary, target)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        return validated_snapshot

    def load(self, frame_id: str) -> RecoverySnapshot:
        path = self.path_for(frame_id)
        try:
            with path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, json.JSONDecodeError) as exc:
            raise RecoverySnapshotError(f"cannot read recovery snapshot: {exc}") from exc
        if not isinstance(data, Mapping):
            raise RecoverySnapshotError("recovery snapshot root must be an object")
        snapshot = RecoverySnapshot.from_dict(data)
        if snapshot.frame_id != frame_id:
            raise RecoverySnapshotError("recovery frame_id does not match its filename")
        return snapshot

    def inspect(self, frame_id: str) -> RecoveryReadResult:
        path = self.path_for(frame_id)
        if not path.is_file():
            return RecoveryReadResult(None)
        try:
            return RecoveryReadResult(self.load(frame_id))
        except RecoverySnapshotError as exc:
            return RecoveryReadResult(None, str(exc))

    def is_newer_than_working(self, frame_id: str, working_label_path: Path) -> bool:
        recovery_path = self.path_for(frame_id)
        if not recovery_path.is_file():
            return False
        working_path = Path(working_label_path)
        if not working_path.is_file():
            return True
        return recovery_path.stat().st_mtime_ns > working_path.stat().st_mtime_ns

    def delete(self, frame_id: str) -> bool:
        try:
            self.path_for(frame_id).unlink()
        except FileNotFoundError:
            return False
        return True

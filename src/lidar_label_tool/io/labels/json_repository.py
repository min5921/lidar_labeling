from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

from lidar_label_tool.domain.labels import FrameLabel


class LabelConflictError(RuntimeError):
    pass


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _safe_component(value: str, name: str) -> str:
    if not value or not _SAFE_COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"{name} must contain only letters, digits, '.', '_' or '-'")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class LabelRepository:
    """Revision-aware atomic repository for working labels."""

    def __init__(self, annotation_dir: Path, dataset_id: str) -> None:
        self.annotation_dir = Path(annotation_dir)
        self.dataset_id = _safe_component(dataset_id, "dataset_id")

    @classmethod
    def for_workspace(cls, workspace_root: Path, dataset_id: str) -> LabelRepository:
        safe_dataset_id = _safe_component(dataset_id, "dataset_id")
        return cls(
            Path(workspace_root) / safe_dataset_id / "annotations" / "lidar_label_tool",
            safe_dataset_id,
        )

    @classmethod
    def for_sidecar(cls, dataset_root: Path, dataset_id: str) -> LabelRepository:
        return cls(Path(dataset_root) / "annotations" / "lidar_label_tool", dataset_id)

    def path_for(self, frame_id: str) -> Path:
        _safe_component(frame_id, "frame_id")
        return self.annotation_dir / f"{frame_id}.json"

    def exists(self, frame_id: str) -> bool:
        return self.path_for(frame_id).is_file()

    def load(self, frame_id: str) -> FrameLabel:
        path = self.path_for(frame_id)
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        label = FrameLabel.from_dict(data)
        if label.dataset_id != self.dataset_id or label.frame_id != frame_id:
            raise ValueError(f"working label identity mismatch: {path}")
        return label

    def save(self, label: FrameLabel) -> FrameLabel:
        if label.dataset_id != self.dataset_id:
            raise ValueError("label dataset_id does not match repository")
        target = self.path_for(label.frame_id)
        target.parent.mkdir(parents=True, exist_ok=True)

        disk_revision = 0
        initial_fingerprint: str | None = None
        if target.exists():
            disk_label = self.load(label.frame_id)
            disk_revision = disk_label.revision
            initial_fingerprint = _sha256(target)
        if disk_revision != label.revision:
            raise LabelConflictError(
                f"working label changed on disk: expected revision {label.revision}, "
                f"found {disk_revision}"
            )

        saved = label.with_saved_revision(disk_revision + 1)
        payload = saved.to_dict()
        token = uuid4().hex
        temporary = target.with_name(f".{target.name}.{token}.tmp")
        backup_temporary = target.with_name(f".{target.name}.{token}.bak.tmp")
        backup = target.with_suffix(target.suffix + ".bak")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())

            with temporary.open("r", encoding="utf-8") as stream:
                validated = FrameLabel.from_dict(json.load(stream))
            if validated.revision != saved.revision:
                raise ValueError("temporary label revision validation failed")

            if target.exists():
                if initial_fingerprint is None or _sha256(target) != initial_fingerprint:
                    raise LabelConflictError("working label changed during save")
                shutil.copy2(target, backup_temporary)
                os.replace(backup_temporary, backup)
            elif initial_fingerprint is not None:
                raise LabelConflictError("working label was removed during save")
            os.replace(temporary, target)
        finally:
            for path in (temporary, backup_temporary):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        return saved

    def load_backup(self, frame_id: str) -> FrameLabel:
        backup = self.path_for(frame_id).with_suffix(".json.bak")
        with backup.open("r", encoding="utf-8") as stream:
            return FrameLabel.from_dict(json.load(stream))

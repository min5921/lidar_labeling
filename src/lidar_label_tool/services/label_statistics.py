from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from lidar_label_tool.domain.labels import FRAME_STATUSES, FrameLabel, LabeledObject
from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.recovery import RecoveryStore


@dataclass(frozen=True, slots=True)
class LabelStatistics:
    dataset_id: str
    mode: str
    frame_count: int
    visited_count: int
    status_counts: tuple[tuple[str, int], ...]
    object_count: int
    class_counts: tuple[tuple[str, int], ...]
    average_objects_per_frame: float
    min_objects_per_frame: int
    max_objects_per_frame: int
    working_label_count: int
    source_label_count: int
    recovery_snapshot_count: int

    def to_dict(self) -> dict[str, Any]:
        statuses = dict(self.status_counts)
        return {
            "dataset_id": self.dataset_id,
            "mode": self.mode,
            "frame_count": self.frame_count,
            "visited_count": self.visited_count,
            "status_counts": statuses,
            "completed_count": statuses.get("reviewed", 0),
            "object_count": self.object_count,
            "class_counts": dict(self.class_counts),
            "average_objects_per_frame": self.average_objects_per_frame,
            "min_objects_per_frame": self.min_objects_per_frame,
            "max_objects_per_frame": self.max_objects_per_frame,
            "working_label_count": self.working_label_count,
            "source_label_count": self.source_label_count,
            "recovery_snapshot_count": self.recovery_snapshot_count,
        }


def collect_label_statistics(
    dataset_root: Path,
    *,
    class_mapping: Mapping[str, str],
    working: bool = False,
    workspace_root: Path | None = None,
) -> LabelStatistics:
    """Collect source-only or working-only frame statistics without writing data."""
    root = Path(dataset_root).resolve()
    adapter = open_dataset_adapter(root)
    index = adapter.scan()
    repository = (
        LabelRepository.for_workspace(workspace_root, index.dataset_id)
        if workspace_root is not None
        else LabelRepository.for_sidecar(root, index.dataset_id)
    )
    importer = WaymoLabelImporter(
        class_mapping,
        source_format=(
            "device_centric_json"
            if isinstance(adapter, DeviceCentricAdapter)
            else "waymo_frame_json"
        ),
    )
    object_counts: list[int] = []
    class_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    source_label_count = 0
    working_label_count = 0

    for frame_id in index.frame_ids:
        source = adapter.load_source_frame(frame_id)
        if "laser" in source.source_label_paths:
            source_label_count += 1
        if not working:
            label_path = source.source_label_paths.get("laser")
            objects: tuple[LabeledObject, ...]
            try:
                if label_path is None:
                    objects = ()
                else:
                    with label_path.open("r", encoding="utf-8") as stream:
                        raw_objects = json.load(stream)
                    if not isinstance(raw_objects, list):
                        raise ValueError("source laser label root must be a list")
                    objects = importer.import_laser_objects(raw_objects)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise ValueError(
                    f"cannot collect source stats for {frame_id}: {type(exc).__name__}: {exc}"
                ) from exc
            if repository.exists(frame_id):
                working_label_count += 1
            object_counts.append(len(objects))
            class_counts.update(obj.class_name for obj in objects)
            status_counts["unvisited"] += 1
            continue

        label: FrameLabel | None
        if repository.exists(frame_id):
            try:
                label = repository.load(frame_id)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ValueError(
                    f"cannot collect working stats for {frame_id}: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            working_label_count += 1
        else:
            label = None

        if label is None:
            object_counts.append(0)
            status_counts["unvisited"] += 1
            continue
        object_counts.append(len(label.objects))
        class_counts.update(obj.class_name for obj in label.objects)
        status_counts[label.frame_status] += 1

    for status in FRAME_STATUSES:
        status_counts.setdefault(status, 0)
    recovery_store = RecoveryStore(repository.annotation_dir)
    recovery_count = (
        sum(1 for _ in recovery_store.recovery_dir.glob("*.recovery.json"))
        if recovery_store.recovery_dir.is_dir()
        else 0
    )
    frame_count = index.frame_count
    object_count = sum(object_counts)
    return LabelStatistics(
        dataset_id=index.dataset_id,
        mode="working" if working else "source",
        frame_count=frame_count,
        visited_count=frame_count - status_counts["unvisited"],
        status_counts=tuple(sorted(status_counts.items())),
        object_count=object_count,
        class_counts=tuple(sorted(class_counts.items())),
        average_objects_per_frame=(object_count / frame_count if frame_count else 0.0),
        min_objects_per_frame=min(object_counts, default=0),
        max_objects_per_frame=max(object_counts, default=0),
        working_label_count=working_label_count,
        source_label_count=source_label_count,
        recovery_snapshot_count=recovery_count,
    )

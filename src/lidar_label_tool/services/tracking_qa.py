from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
import math
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Mapping

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.io.dataset import DatasetAdapter
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter, sha256_file
from lidar_label_tool.services.background_task import TaskControl
from lidar_label_tool.services.object_tracking import TrackingOptions, TrackingRequest, track_object


@dataclass(frozen=True, slots=True)
class TrackingQaOptions:
    max_frames: int = 4
    max_objects_per_pair: int = 12
    start_index: int = 0
    max_distance_m: float = 4.0

    def __post_init__(self) -> None:
        if self.max_frames < 2 or self.max_objects_per_pair < 1 or self.start_index < 0:
            raise ValueError("max_frames >= 2, max_objects_per_pair >= 1, start_index >= 0 are required")
        TrackingOptions(max_distance_m=self.max_distance_m)


def _balanced_objects(objects: Iterable[LabeledObject], limit: int) -> tuple[LabeledObject, ...]:
    """Deterministic class round-robin avoids using a budget only on the first vehicle class."""
    by_class: dict[str, list[LabeledObject]] = defaultdict(list)
    for obj in sorted(objects, key=lambda item: (item.class_name, item.id)):
        by_class[obj.class_name].append(obj)
    result: list[LabeledObject] = []
    offset = 0
    while len(result) < limit:
        additions = [items[offset] for items in by_class.values() if offset < len(items)]
        if not additions:
            break
        result.extend(additions[:limit - len(result)])
        offset += 1
    return tuple(result)


def _distance(first: Box3D, second: Box3D) -> float:
    return math.dist((first.x, first.y, first.z), (second.x, second.y, second.z))


def _errors_summary(values: list[float]) -> dict[str, float | None]:
    return {
        "mean": mean(values) if values else None,
        "median": median(values) if values else None,
        "max": max(values) if values else None,
    }


def _class_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = [sample for sample in samples if sample["status"] == "matched"]
    return {
        "sample_count": len(samples),
        "accepted_count": len(accepted),
        "fallback_count": len(samples) - len(accepted),
        "status_counts": dict(sorted(Counter(sample["status"] for sample in samples).items())),
        "accepted_center_error_m": _errors_summary([sample["center_error_m"] for sample in accepted]),
        "accepted_z_error_m": _errors_summary([sample["z_error_m"] for sample in accepted]),
        "all_prediction_center_error_m": _errors_summary([sample["center_error_m"] for sample in samples]),
        "unchanged_box_center_error_m": _errors_summary([sample["baseline_center_error_m"] for sample in samples]),
    }


def validate_tracking_sample(
    adapter: DatasetAdapter,
    class_mapping: Mapping[str, str],
    *,
    lidar_id: str,
    options: TrackingQaOptions | None = None,
    control: TaskControl | None = None,
) -> dict[str, Any]:
    """Read-only reference-label comparison for bounded adjacent-frame samples.

    Reads source labels only, never working labels or a repository. The future label's
    objects are withheld from tracking, then used only to measure center error. Uses one
    explicit LiDAR, preserves its declared coordinates, and never applies ground snapping.
    This is sample QA against existing annotations, not independent ground-truth certification.
    """
    limits = options or TrackingQaOptions()
    task = control or TaskControl()
    index = adapter.scan()
    if lidar_id not in index.lidar_ids:
        raise ValueError(f"unknown LiDAR {lidar_id!r}; available: {index.lidar_ids}")
    frame_ids = index.frame_ids[limits.start_index:limits.start_index + limits.max_frames]
    if len(frame_ids) < 2:
        raise ValueError("at least two adjacent frames are required for QA")
    importer = WaymoLabelImporter(class_mapping)
    inputs: dict[Path, str] = {}
    samples: list[dict[str, Any]] = []
    pair_summaries: list[dict[str, Any]] = []

    def fingerprint(paths: Iterable[Path]) -> None:
        for path in paths:
            task.check_cancelled()
            if path not in inputs:
                inputs[path] = sha256_file(path)

    def load(frame_id: str) -> tuple[FrameLabel, tuple[PointCloudData, ...]]:
        source = adapter.load_source_frame(frame_id)
        paths = source.point_cloud_paths.get(lidar_id, ())
        if not paths:
            raise ValueError(f"frame {frame_id} has no point files for {lidar_id}")
        source_label = source.source_label_paths.get("laser")
        if source_label is None:
            raise ValueError(f"frame {frame_id} has no source laser labels for reference QA")
        fingerprint((*paths, source_label))
        label = importer.import_laser_labels(source)
        clouds = tuple(adapter.load_cloud_from_source(source, lidar_id, str(i + 1)) for i in range(len(paths)))
        if any(cloud.source_frame != label.reference_frame for cloud in clouds):
            raise ValueError("point and source box coordinates differ; QA never guesses a transform")
        return replace(label, point_cloud_paths={lidar_id: label.point_cloud_paths[lidar_id]}), clouds

    source_label, source_clouds = load(frame_ids[0])
    for pair_index, target_id in enumerate(frame_ids[1:]):
        task.check_cancelled()
        target_label, target_clouds = load(target_id)
        target_objects = {obj.id: obj for obj in target_label.objects}
        eligible = [
            obj for obj in source_label.objects
            if obj.id in target_objects and obj.class_name == target_objects[obj.id].class_name
        ]
        selected = _balanced_objects(eligible, limits.max_objects_per_pair)
        pair_summaries.append({
            "source_frame_id": source_label.frame_id, "target_frame_id": target_id,
            "eligible_shared_objects": len(eligible), "sampled_objects": len(selected),
            "source_point_count": sum(cloud.point_count for cloud in source_clouds),
            "target_point_count": sum(cloud.point_count for cloud in target_clouds),
        })
        # Target labels are evaluation references only, not tracker initialization.
        unlabeled_target = replace(target_label, objects=())
        for obj in selected:
            task.check_cancelled()
            reference = target_objects[obj.id]
            request = TrackingRequest(
                index.dataset_id, source_label.frame_id, target_id, source_label.reference_frame,
                (lidar_id,), obj, source_clouds,
                TrackingOptions(max_distance_m=limits.max_distance_m, adjust_z=True, ground_contact=False),
            )
            result = track_object(request, unlabeled_target, target_clouds)
            if any(getattr(result.box, key) != getattr(obj.box3d, key) for key in ("length", "width", "height", "yaw")):
                raise AssertionError("tracking changed box dimensions/yaw")
            if result.status != "matched" and result.box != obj.box3d:
                raise AssertionError("tracking fallback moved the original box")
            if result.ground_contact or result.ground_applied:
                raise AssertionError("reference QA must not ground-snap suspended objects")
            samples.append({
                "source_frame_id": source_label.frame_id, "target_frame_id": target_id,
                "object_id": obj.id, "class_name": obj.class_name,
                "status": result.status, "score": result.score,
                "center_error_m": _distance(result.box, reference.box3d),
                "z_error_m": abs(result.box.z - reference.box3d.z),
                "baseline_center_error_m": _distance(obj.box3d, reference.box3d),
                "predicted_delta_xyz": [getattr(result.box, key) - getattr(obj.box3d, key) for key in ("x", "y", "z")],
                "reference_delta_xyz": [getattr(reference.box3d, key) - getattr(obj.box3d, key) for key in ("x", "y", "z")],
            })
        task.report("tracking_qa", pair_index + 1, len(frame_ids) - 1, f"{source_label.frame_id} → {target_id}: {len(selected)}개 비교")
        source_label, source_clouds = target_label, target_clouds
    for path, expected in inputs.items():
        task.check_cancelled()
        if sha256_file(path) != expected:
            raise ValueError(f"input changed during QA; comparison is invalid: {path}")
    class_names = sorted({sample["class_name"] for sample in samples})
    return {
        "report_type": "read_only_tracking_reference_qa",
        "warning": "기존 source 라벨과의 제한된 표본 비교이며 독립적인 정답/추적 정확도 인증이 아닙니다. 실제 작업 결과는 사용자 검토가 필요합니다.",
        "dataset_id": index.dataset_id, "adapter": index.adapter_name,
        "lidar_id": lidar_id, "frame_ids": list(frame_ids),
        "max_objects_per_pair": limits.max_objects_per_pair,
        "selection": "class_round_robin_then_object_id",
        "tracking_options": {"max_distance_m": limits.max_distance_m, "adjust_z": True, "ground_contact": False},
        "source_integrity": "unchanged", "verified_input_file_count": len(inputs),
        "size_yaw_invariant": "passed", "fallback_position_invariant": "passed",
        "summary": _class_summary(samples),
        "by_class": {name: _class_summary([sample for sample in samples if sample["class_name"] == name]) for name in class_names},
        "pairs": pair_summaries, "samples": samples,
    }

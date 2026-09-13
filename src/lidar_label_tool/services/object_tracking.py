from __future__ import annotations

from dataclasses import dataclass, field, replace
from copy import deepcopy
import logging
import math
from threading import Event
from typing import Iterable

import numpy as np

from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject, utc_now_iso
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.geometry.box_fit import fit_box_to_local_ground
from lidar_label_tool.geometry.point_selection import points_in_box


@dataclass(frozen=True, slots=True)
class TrackingOptions:
    max_distance_m: float = 4.0
    adjust_z: bool = True
    max_z_step_m: float = 0.6
    ground_contact: bool = False
    retrack_existing: bool = False

    def __post_init__(self) -> None:
        if not math.isfinite(self.max_distance_m) or not 0.5 <= self.max_distance_m <= 10:
            raise ValueError("tracking distance must be between 0.5 and 10 meters")
        if not math.isfinite(self.max_z_step_m) or not 0 < self.max_z_step_m <= 1:
            raise ValueError("tracking z limit must be between 0 and 1 meter")


@dataclass(frozen=True, slots=True)
class TrackingRequest:
    dataset_id: str
    source_frame_id: str
    target_frame_id: str
    reference_frame: str
    lidar_ids: tuple[str, ...]
    obj: LabeledObject
    clouds: tuple[PointCloudData, ...]
    options: TrackingOptions = field(default_factory=TrackingOptions)
    cancel: Event = field(default_factory=Event, compare=False)


@dataclass(frozen=True, slots=True)
class TrackingResult:
    object_id: str
    source_frame_id: str
    target_frame_id: str
    box: Box3D
    status: str
    message: str
    score: float = 0.0
    adjust_z: bool = False
    ground_contact: bool = False
    ground_applied: bool = False
    expected_target_object: LabeledObject | None = None


def track_object(
    request: TrackingRequest,
    target: FrameLabel,
    clouds: Iterable[PointCloudData],
) -> TrackingResult:
    """Estimate one selected box's translation from raw reference-frame clouds.

    Uses bounded voxel samples and local translation matching, not learned tracking.
    Suspended objects keep their point-to-box offset unless ground contact is explicitly
    enabled for this object. Size/yaw, [N,3] float32 clouds and source labels stay unchanged.
    Call in a worker. Existing boxes require explicit opt-in and an unreviewed frame;
    their dimensions/metadata remain authoritative. Failure keeps the existing box.
    """
    existing = next((obj for obj in target.objects if obj.id == request.obj.id), None)
    prior_box = existing.box3d if existing is not None else request.obj.box3d

    def result(
        status: str, message: str, box: Box3D | None = None, score: float = 0
    ) -> TrackingResult:
        return TrackingResult(
            request.obj.id,
            request.source_frame_id,
            request.target_frame_id,
            box or prior_box,
            status,
            message,
            score,
            request.options.adjust_z,
            request.options.ground_contact,
            expected_target_object=(
                deepcopy(existing) if request.options.retrack_existing else None
            ),
        )

    if request.cancel.is_set():
        return result("cancelled", "추적 취소")
    target_clouds = tuple(clouds)
    if (
        target.dataset_id != request.dataset_id
        or target.frame_id != request.target_frame_id
        or target.reference_frame != request.reference_frame
        or tuple(sorted(target.point_cloud_paths)) != request.lidar_ids
        or len(request.lidar_ids) != 1
        or any(
            cloud.source_frame != request.reference_frame
            or cloud.sensor_id not in request.lidar_ids
            for cloud in (*request.clouds, *target_clouds)
        )
    ):
        return result("incompatible", "같은 단일 LiDAR·좌표계에서만 추적할 수 있습니다")
    if existing is not None:
        if not request.options.retrack_existing:
            return result("existing_label", "기존 동일 ID 유지 — 필요 시 ‘기존 박스도 다시 추적’을 켜세요")
        if target.frame_status in {"reviewed", "skipped"}:
            return result("protected_label", "검토 완료/건너뜀 프레임의 기존 라벨 유지")
        if existing.class_name != request.obj.class_name:
            return result("incompatible_object", "동일 ID의 클래스가 달라 기존 라벨 유지")
        if not isinstance(existing.extra_fields.get("tracking_history", []), list):
            return result("invalid_history", "대상 추적 이력 형식 오류 — 기존 라벨 유지")
    if not isinstance(request.obj.extra_fields.get("tracking_history", []), list):
        return result("invalid_history", "기존 추적 이력 형식 오류 — 위치 유지")
    box, options = request.obj.box3d, request.options
    source_parts = []
    target_parts = []
    # Exclude the bottom band so road points cannot dominate a vehicle template.
    bottom = box.z - box.height / 2 + min(0.15, box.height * 0.1)
    radius_x = abs(math.cos(box.yaw)) * box.length / 2 + abs(math.sin(box.yaw)) * box.width / 2
    radius_y = abs(math.sin(box.yaw)) * box.length / 2 + abs(math.cos(box.yaw)) * box.width / 2
    for cloud in request.clouds:
        if request.cancel.is_set():
            return result("cancelled", "추적 취소")
        mask = points_in_box(cloud.xyz, box) & (cloud.xyz[:, 2] > bottom)
        source_parts.append(cloud.xyz[mask])
    for cloud in target_clouds:
        if request.cancel.is_set():
            return result("cancelled", "추적 취소")
        xyz = cloud.xyz
        mask = (
            np.isfinite(xyz).all(axis=1)
            & (np.abs(xyz[:, 0] - box.x) <= radius_x + options.max_distance_m)
            & (np.abs(xyz[:, 1] - box.y) <= radius_y + options.max_distance_m)
            & (np.abs(xyz[:, 2] - box.z) <= box.height / 2 + options.max_z_step_m + 0.2)
        )
        target_parts.append(xyz[mask])
    source = _voxel_sample(source_parts, 160)
    target_points = _voxel_sample(target_parts, 2400)
    if len(source) < 12 or len(target_points) < 12:
        return result("insufficient_points", "객체 포인트 부족 — 기존 위치 유지")
    # Work near zero for accurate float32 distances even in large reference coordinates.
    origin = np.array([box.x, box.y, box.z], dtype=np.float64)
    source = np.asarray(source - origin, dtype=np.float32)
    target_points = np.asarray(target_points - origin, dtype=np.float32)
    local_box = replace(box, x=0, y=0, z=0)
    matches: list[tuple[float, np.ndarray]] = []
    for seed in _translation_seeds(source, target_points, options):
        if request.cancel.is_set():
            return result("cancelled", "추적 취소")
        score, shift = _refine_translation(source, target_points, local_box, seed, options)
        if score > 0:
            matches.append((score, shift))
    if not matches:
        return result("no_match", "신뢰할 대응 포인트 없음 — 기존 위치 유지")
    matches.sort(key=lambda match: -match[0])
    score, shift = matches[0]
    if score < 0.58:
        return result("low_confidence", "추적 신뢰도 부족 — 기존 위치 유지", score=score)
    if np.linalg.norm(shift[:2]) >= options.max_distance_m - 0.15:
        return result("search_boundary", "검색 범위 경계의 후보 — 기존 위치 유지", score=score)
    if options.adjust_z and abs(shift[2]) >= options.max_z_step_m - 0.03:
        return result("z_boundary", "상하 이동 제한의 후보 — 기존 위치 유지", score=score)
    if any(
        np.linalg.norm(other_shift - shift) > 0.6 and score - other_score < 0.07
        for other_score, other_shift in matches[1:]
    ):
        return result("ambiguous", "비슷한 추적 후보가 여러 개 — 기존 위치 유지", score=score)
    fitted = replace(
        prior_box, x=box.x + float(shift[0]), y=box.y + float(shift[1]),
        z=box.z + float(shift[2]) if options.adjust_z else prior_box.z,
    )
    outcome = result("matched", "객체 포인트 이동량으로 위치 조정", fitted, score)
    if options.adjust_z and options.ground_contact:
        # Ground fitting is opt-in per object. Failed fitting keeps its prior z.
        ground = fit_box_to_local_ground(
            replace(fitted, z=prior_box.z),
            target_clouds,
            max_z_step_m=options.max_z_step_m,
        )
        outcome = replace(
            outcome,
            box=ground or replace(fitted, z=prior_box.z),
            ground_applied=ground is not None,
            message="x/y 추적 · 지면 기준 z 보정"
            if ground is not None
            else "x/y 추적 · 지면 추정 불확실: 기존 z 유지",
        )
    if existing is not None:
        outcome = replace(outcome, message=f"기존 박스 재추적 · {outcome.message}")
    return outcome


def _voxel_sample(parts: list[np.ndarray], limit: int) -> np.ndarray:
    if not parts or not any(len(part) for part in parts):
        return np.empty((0, 3), dtype=np.float32)
    points = np.concatenate(parts)
    keys = np.floor((points.astype(np.float64) - points.min(axis=0)) / 0.12).astype(np.int64)
    _, indices = np.unique(keys, axis=0, return_index=True)
    if len(indices) > limit:
        indices = indices[np.linspace(0, len(indices) - 1, limit, dtype=int)]
    return points[indices]


def _translation_seeds(
    source: np.ndarray, target: np.ndarray, options: TrackingOptions
) -> list[np.ndarray]:
    step = 0.2
    differences = (target[:, None, :] - source[None, :, :]).reshape(-1, 3)
    mask = (np.linalg.norm(differences[:, :2], axis=1) <= options.max_distance_m) & (
        np.abs(differences[:, 2]) <= (options.max_z_step_m if options.adjust_z else 0.25)
    )
    differences = differences[mask]
    if not options.adjust_z:
        differences[:, 2] = 0
    cells = np.rint(differences / step).astype(np.int32)
    unique, counts = np.unique(cells, axis=0, return_counts=True)
    seeds = [np.zeros(3, dtype=np.float32)]
    for index in np.argsort(-counts, kind="stable"):
        shift = unique[index].astype(np.float32) * step
        if all(np.linalg.norm(shift - old) >= 0.45 for old in seeds):
            seeds.append(shift)
        if len(seeds) >= 24:
            break
    return seeds


def _squared_distances(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    delta = source[:, None, :] - target[None, :, :]
    return np.einsum("ijk,ijk->ij", delta, delta)


def _refine_translation(
    source: np.ndarray,
    target: np.ndarray,
    box: Box3D,
    seed: np.ndarray,
    options: TrackingOptions,
) -> tuple[float, np.ndarray]:
    shift = seed.copy()
    for _ in range(6):
        distances = _squared_distances(source + shift, target)
        nearest = distances.argmin(axis=1)
        minimum = distances[np.arange(len(source)), nearest]
        valid = minimum <= 0.45**2
        if np.count_nonzero(valid) < max(8, int(len(source) * 0.4)):
            return 0.0, shift
        delta = np.median(target[nearest[valid]] - (source[valid] + shift), axis=0)
        if not options.adjust_z:
            delta[2] = 0
        shift += delta
        if (
            np.linalg.norm(shift[:2]) > options.max_distance_m
            or abs(shift[2]) > options.max_z_step_m
        ):
            return 0.0, shift
        if np.linalg.norm(delta) < 0.01:
            break
    distances = _squared_distances(source + shift, target)
    forward = distances.min(axis=1)
    moved_box = replace(box, x=float(shift[0]), y=float(shift[1]), z=float(shift[2]))
    inside = points_in_box(target, moved_box, margin_m=0.1)
    # Use the same above-bottom support band as the source template.
    inside &= target[:, 2] > moved_box.z - box.height / 2 + min(0.15, box.height * 0.1)
    if np.count_nonzero(inside) < 12:
        return 0.0, shift
    backward = distances[:, inside].min(axis=0)
    coverage = float(np.mean(forward <= 0.25**2))
    purity = float(np.mean(backward <= 0.25**2))
    if coverage < 0.6 or purity < 0.55:
        return 0.0, shift
    score = 2 * coverage * purity / (coverage + purity)
    score *= 1 - min(float(np.sqrt(np.median(forward))) / 0.5, 0.8)
    return score, shift


def apply_tracking_result(
    label: FrameLabel, result: TrackingResult, *, retrack_existing: bool = False,
) -> FrameLabel:
    """Apply an adjustment to a carried object or an explicitly approved target snapshot."""
    if result.status != "matched" or label.frame_id != result.target_frame_id:
        return label
    obj = next((item for item in label.objects if item.id == result.object_id), None)
    if obj is None:
        return label
    if result.expected_target_object is not None and (
        not retrack_existing
        or label.frame_status in {"reviewed", "skipped"}
        or obj != result.expected_target_object
    ):
        return label
    box = result.box
    if result.expected_target_object is not None:
        box = replace(
            obj.box3d, x=box.x, y=box.y,
            z=box.z if result.adjust_z else obj.box3d.z,
        )
    history = obj.extra_fields.get("tracking_history", [])
    if not isinstance(history, list):
        logging.getLogger(__name__).warning("Malformed tracking history: %s", obj.id)
        return label
    fields = dict(obj.extra_fields)
    # Each earlier frame already stores its own tracking record. Do not accumulate
    # an O(frame_count**2) journal in every subsequent file; retain unknown entries.
    retained = [
        item
        for item in history
        if not (isinstance(item, dict) and item.get("method") == "local_point_translation")
    ]
    fields["tracking_history"] = [
        *retained,
        {
            "method": "local_point_translation",
            "source_frame_id": result.source_frame_id,
            "target_frame_id": result.target_frame_id,
            "score": result.score,
            "adjust_z": result.adjust_z,
            "applied_at_utc": utc_now_iso(),
            "ground_contact": result.ground_contact,
            "ground_applied": result.ground_applied,
            **({"retracked_existing": True} if result.expected_target_object is not None else {}),
            "delta_xyz": [
                getattr(box, key) - getattr(obj.box3d, key) for key in ("x", "y", "z")
            ],
        },
    ]
    edited = replace(obj, box3d=box, extra_fields=fields)
    return replace(
        label,
        objects=tuple(edited if item.id == obj.id else item for item in label.objects),
        frame_status="in_progress",
    )

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass
import hashlib
import math
import re
from typing import Iterable

from lidar_label_tool.domain.dataset_v2 import (
    FrameCameraSampleV2,
    FrameIndexRecordV2,
    FrameLidarSampleV2,
    FrameMatchV2,
    MatchStatus,
    SyncMethod,
)
from lidar_label_tool.services.timestamp_table import TimestampTable


_MACHINE_ID = re.compile(
    r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$))"
    r"[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9_-])?$"
)


class SynchronizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class SensorSample:
    sensor_id: str
    source_sample_id: str
    relative_path: str
    logical_sample_id: str

    @classmethod
    def create(
        cls,
        *,
        sensor_id: str,
        source_sample_id: str,
        relative_path: str,
    ) -> SensorSample:
        return cls(
            sensor_id=sensor_id,
            source_sample_id=source_sample_id,
            relative_path=relative_path,
            logical_sample_id=logical_sample_id(
                sensor_id,
                source_sample_id,
                relative_path,
            ),
        )


@dataclass(frozen=True, slots=True)
class SynchronizationQa:
    method: SyncMethod
    lidar_frame_count: int
    matched_camera_count: int
    unmatched_camera_count: int
    camera_sample_reuse_count: int
    max_camera_sample_usage: int
    max_camera_repeat_run: int
    mean_abs_delta_ns: float | None
    p95_abs_delta_ns: int | None
    max_abs_delta_ns: int | None
    lidar_reordered_rows: int
    camera_reordered_rows: int
    lidar_duplicate_timestamps: int
    camera_duplicate_timestamps: int
    camera_samples_without_timestamp: int

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "lidar_frame_count": self.lidar_frame_count,
            "matched_camera_count": self.matched_camera_count,
            "unmatched_camera_count": self.unmatched_camera_count,
            "camera_sample_reuse_count": self.camera_sample_reuse_count,
            "max_camera_sample_usage": self.max_camera_sample_usage,
            "max_camera_repeat_run": self.max_camera_repeat_run,
            "mean_abs_delta_ns": self.mean_abs_delta_ns,
            "p95_abs_delta_ns": self.p95_abs_delta_ns,
            "max_abs_delta_ns": self.max_abs_delta_ns,
            "lidar_reordered_rows": self.lidar_reordered_rows,
            "camera_reordered_rows": self.camera_reordered_rows,
            "lidar_duplicate_timestamps": self.lidar_duplicate_timestamps,
            "camera_duplicate_timestamps": self.camera_duplicate_timestamps,
            "camera_samples_without_timestamp": self.camera_samples_without_timestamp,
        }


@dataclass(frozen=True, slots=True)
class SynchronizationResult:
    records: tuple[FrameIndexRecordV2, ...]
    qa: SynchronizationQa


def logical_sample_id(
    sensor_id: str,
    source_sample_id: str,
    relative_path: str,
) -> str:
    if _MACHINE_ID.fullmatch(source_sample_id):
        return source_sample_id
    digest = hashlib.sha256(
        f"{sensor_id}\0{source_sample_id}\0{relative_path}".encode("utf-8")
    ).hexdigest()
    return "s_" + digest[:62]


def make_sensor_samples(
    sensor_id: str,
    samples: Iterable[tuple[str, str]],
) -> tuple[SensorSample, ...]:
    result = tuple(
        SensorSample.create(
            sensor_id=sensor_id,
            source_sample_id=source_sample_id,
            relative_path=relative_path,
        )
        for source_sample_id, relative_path in samples
    )
    _require_unique(result, "source_sample_id")
    _require_unique(result, "logical_sample_id")
    _require_unique(result, "relative_path")
    return result


def synchronize_profile(
    *,
    profile_id: str,
    lidar_samples: tuple[SensorSample, ...],
    method: SyncMethod,
    camera_samples: tuple[SensorSample, ...] = (),
    lidar_timestamps: TimestampTable | None = None,
    camera_timestamps: TimestampTable | None = None,
    tolerance_ns: int | None = None,
) -> SynchronizationResult:
    if not lidar_samples:
        raise SynchronizationError("no_lidar_samples", "at least one LiDAR sample is required")
    _require_unique(lidar_samples, "source_sample_id")
    _require_unique(lidar_samples, "logical_sample_id")
    _require_unique(camera_samples, "source_sample_id")
    _require_unique(camera_samples, "logical_sample_id")
    if method == "lidar_only":
        if camera_samples or camera_timestamps is not None or tolerance_ns is not None:
            raise SynchronizationError(
                "lidar_only_camera_configured",
                "lidar_only cannot have camera samples, timestamps, or tolerance",
            )
    elif method == "exact_stem":
        if not camera_samples:
            raise SynchronizationError(
                "camera_samples_missing", "exact_stem requires camera samples"
            )
        if tolerance_ns is not None:
            raise SynchronizationError(
                "sync_tolerance_invalid", "exact_stem tolerance must be null"
            )
    elif method == "timestamp_nearest":
        if not camera_samples or lidar_timestamps is None or camera_timestamps is None:
            raise SynchronizationError(
                "timestamp_config_incomplete",
                "timestamp_nearest requires camera samples and both timestamp tables",
            )
        if lidar_timestamps.clock_domain != camera_timestamps.clock_domain:
            raise SynchronizationError(
                "clock_domain_mismatch",
                f"{lidar_timestamps.clock_domain!r} != {camera_timestamps.clock_domain!r}",
            )
        if tolerance_ns is None or tolerance_ns < 0:
            raise SynchronizationError(
                "sync_tolerance_invalid", "timestamp_nearest requires non-negative tolerance"
            )
    else:
        raise SynchronizationError("sync_method_invalid", f"unsupported method: {method}")

    lidar_times = _timestamps_for_lidar(lidar_samples, lidar_timestamps, method)
    ordered_lidar = sorted(
        lidar_samples,
        key=lambda sample: _lidar_sort_key(sample, lidar_times),
    )
    camera_by_source = {sample.source_sample_id: sample for sample in camera_samples}
    nearest = _NearestCameraIndex(camera_samples, camera_timestamps)
    records: list[FrameIndexRecordV2] = []
    matched_ids: list[str] = []
    matched_sequence: list[str | None] = []
    abs_deltas: list[int] = []

    for ordinal, lidar in enumerate(ordered_lidar):
        lidar_time = lidar_times.get(lidar.source_sample_id)
        camera: FrameCameraSampleV2 | None = None
        status: MatchStatus = "not_requested" if method == "lidar_only" else "unmatched"
        matched_logical_id: str | None = None
        if method == "exact_stem":
            exact_selected = camera_by_source.get(lidar.source_sample_id)
            if exact_selected is not None:
                camera_time = _timestamp_for(
                    camera_timestamps, exact_selected.source_sample_id
                )
                camera = _camera_record(exact_selected, camera_time, None)
                status = "matched"
                matched_logical_id = exact_selected.logical_sample_id
                matched_ids.append(matched_logical_id)
        elif method == "timestamp_nearest":
            assert lidar_time is not None
            assert tolerance_ns is not None
            nearest_selected = nearest.closest(lidar_time)
            if nearest_selected is not None:
                selected_sample, camera_time = nearest_selected
                delta = camera_time - lidar_time
                if abs(delta) <= tolerance_ns:
                    camera = _camera_record(selected_sample, camera_time, delta)
                    status = "matched"
                    matched_logical_id = selected_sample.logical_sample_id
                    matched_ids.append(matched_logical_id)
                    abs_deltas.append(abs(delta))
        matched_sequence.append(matched_logical_id)
        records.append(
            FrameIndexRecordV2(
                profile_id=profile_id,
                ordinal=ordinal,
                frame_id=lidar.logical_sample_id,
                lidar=FrameLidarSampleV2(
                    sensor_id=lidar.sensor_id,
                    sample_id=lidar.logical_sample_id,
                    source_sample_id=lidar.source_sample_id,
                    path=lidar.relative_path,
                    timestamp_ns=lidar_time,
                ),
                camera=camera,
                match=FrameMatchV2(
                    method=method,
                    status=status,
                    tolerance_ns=tolerance_ns,
                ),
            )
        )

    usage = Counter(matched_ids)
    qa = SynchronizationQa(
        method=method,
        lidar_frame_count=len(records),
        matched_camera_count=len(matched_ids),
        unmatched_camera_count=(
            0 if method == "lidar_only" else len(records) - len(matched_ids)
        ),
        camera_sample_reuse_count=sum(count - 1 for count in usage.values()),
        max_camera_sample_usage=max(usage.values(), default=0),
        max_camera_repeat_run=_max_repeat_run(matched_sequence),
        mean_abs_delta_ns=(sum(abs_deltas) / len(abs_deltas) if abs_deltas else None),
        p95_abs_delta_ns=_percentile_nearest_rank(abs_deltas, 0.95),
        max_abs_delta_ns=max(abs_deltas, default=None),
        lidar_reordered_rows=(
            lidar_timestamps.reordered_row_count if lidar_timestamps is not None else 0
        ),
        camera_reordered_rows=(
            camera_timestamps.reordered_row_count if camera_timestamps is not None else 0
        ),
        lidar_duplicate_timestamps=(
            lidar_timestamps.duplicate_timestamp_count
            if lidar_timestamps is not None
            else 0
        ),
        camera_duplicate_timestamps=(
            camera_timestamps.duplicate_timestamp_count
            if camera_timestamps is not None
            else 0
        ),
        camera_samples_without_timestamp=nearest.missing_timestamp_count,
    )
    return SynchronizationResult(tuple(records), qa)


class _NearestCameraIndex:
    def __init__(
        self,
        samples: tuple[SensorSample, ...],
        timestamps: TimestampTable | None,
    ) -> None:
        values: list[tuple[int, bytes, SensorSample]] = []
        missing = 0
        if timestamps is not None:
            for sample in samples:
                timestamp = timestamps.timestamp_for(sample.source_sample_id)
                if timestamp is None:
                    missing += 1
                    continue
                values.append((timestamp, sample.relative_path.encode("utf-8"), sample))
        values.sort(key=lambda item: (item[0], item[1]))
        self.values = tuple(values)
        self.times = tuple(item[0] for item in values)
        self.missing_timestamp_count = missing

    def closest(self, timestamp_ns: int) -> tuple[SensorSample, int] | None:
        if not self.values:
            return None
        position = bisect_left(self.times, timestamp_ns)
        candidate_times: set[int] = set()
        if position < len(self.times):
            candidate_times.add(self.times[position])
        if position > 0:
            candidate_times.add(self.times[position - 1])
        candidates: list[tuple[int, bytes, SensorSample]] = []
        for value in candidate_times:
            start = bisect_left(self.times, value)
            end = bisect_right(self.times, value)
            candidates.extend(self.values[start:end])
        selected = min(
            candidates,
            key=lambda item: (abs(item[0] - timestamp_ns), item[0], item[1]),
        )
        return selected[2], selected[0]


def _timestamps_for_lidar(
    samples: tuple[SensorSample, ...],
    table: TimestampTable | None,
    method: SyncMethod,
) -> dict[str, int]:
    if table is None:
        return {}
    values: dict[str, int] = {}
    missing: list[str] = []
    for sample in samples:
        value = table.timestamp_for(sample.source_sample_id)
        if value is None:
            missing.append(sample.source_sample_id)
        else:
            values[sample.source_sample_id] = value
    if missing and method == "timestamp_nearest":
        preview = ", ".join(repr(value) for value in missing[:5])
        raise SynchronizationError(
            "lidar_timestamp_missing",
            f"LiDAR timestamp rows are missing for {preview}",
        )
    return values


def _lidar_sort_key(sample: SensorSample, timestamps: dict[str, int]) -> tuple[object, ...]:
    timestamp = timestamps.get(sample.source_sample_id)
    if timestamp is not None:
        return (0, timestamp, sample.logical_sample_id.encode("utf-8"))
    return (1, sample.logical_sample_id.encode("utf-8"))


def _timestamp_for(table: TimestampTable | None, source_sample_id: str) -> int | None:
    return table.timestamp_for(source_sample_id) if table is not None else None


def _camera_record(
    sample: SensorSample,
    timestamp_ns: int | None,
    delta_ns: int | None,
) -> FrameCameraSampleV2:
    return FrameCameraSampleV2(
        sensor_id=sample.sensor_id,
        sample_id=sample.logical_sample_id,
        source_sample_id=sample.source_sample_id,
        path=sample.relative_path,
        timestamp_ns=timestamp_ns,
        delta_ns=delta_ns,
    )


def _require_unique(samples: Iterable[SensorSample], field: str) -> None:
    values = [getattr(sample, field) for sample in samples]
    duplicates = sorted(
        (value for value, count in Counter(values).items() if count > 1),
        key=lambda value: str(value).encode("utf-8"),
    )
    if duplicates:
        raise SynchronizationError(
            f"{field}_duplicate",
            f"duplicate {field}: {duplicates[0]!r}",
        )


def _max_repeat_run(values: list[str | None]) -> int:
    maximum = 0
    current = 0
    previous: str | None = None
    for value in values:
        if value is None:
            previous = None
            current = 0
            continue
        if value == previous:
            current += 1
        else:
            previous = value
            current = 1
        maximum = max(maximum, current)
    return maximum


def _percentile_nearest_rank(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    position = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[position]

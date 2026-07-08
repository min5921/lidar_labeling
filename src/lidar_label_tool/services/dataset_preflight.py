from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from lidar_label_tool.io.adapters.device_centric import DeviceCentricAdapter
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.recovery import RecoveryStore


Severity = Literal["info", "warning", "error"]
_USABLE_CALIBRATION_STATES = {"not_required", "applied"}
_SUPPORTED_POINT_EXTENSIONS = {".bin", ".pcd"}


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    severity: Severity
    code: str
    message: str
    frame_id: str | None = None
    sensor_id: str | None = None
    path: Path | None = None

    def __post_init__(self) -> None:
        if self.severity not in {"info", "warning", "error"}:
            raise ValueError(f"unsupported preflight severity: {self.severity}")
        if not self.code or not self.message:
            raise ValueError("preflight issue code and message are required")

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "frame_id": self.frame_id,
            "sensor_id": self.sensor_id,
            "path": str(self.path) if self.path is not None else None,
        }


@dataclass(frozen=True, slots=True)
class SensorAvailability:
    sensor_id: str
    available_frames: int
    missing_frames: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "sensor_id": self.sensor_id,
            "available_frames": self.available_frames,
            "missing_frames": self.missing_frames,
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    dataset_root: Path
    dataset_id: str
    adapter_name: str
    frame_count: int
    usable_frame_count: int
    lidar_ids: tuple[str, ...]
    camera_ids: tuple[str, ...]
    reference_frame: str
    lidar_availability: tuple[SensorAvailability, ...]
    camera_availability: tuple[SensorAvailability, ...]
    frame_cameras: tuple[tuple[str, tuple[str, ...]], ...]
    calibration_states: tuple[tuple[str, str], ...]
    camera_calibration_count: int
    calibration_fingerprint: str | None
    source_label_count: int
    source_object_count: int
    source_class_counts: tuple[tuple[str, int], ...]
    working_label_count: int
    working_revision_min: int | None
    working_revision_max: int | None
    recovery_snapshot_count: int
    issues: tuple[PreflightIssue, ...]

    @property
    def error_count(self) -> int:
        return sum(issue.severity == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.severity == "warning" for issue in self.issues)

    @property
    def info_count(self) -> int:
        return sum(issue.severity == "info" for issue in self.issues)

    @property
    def exit_code(self) -> int:
        if self.error_count:
            return 2
        if self.warning_count:
            return 1
        return 0

    def short_summary_ko(self) -> str:
        return (
            f"프레임 {self.frame_count}개 · 사용 가능 {self.usable_frame_count}개\n"
            f"LiDAR {len(self.lidar_ids)}개 · 카메라 {len(self.camera_ids)}개\n"
            f"오류 {self.error_count}개 · 경고 {self.warning_count}개"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_root": str(self.dataset_root),
            "dataset_id": self.dataset_id,
            "adapter_name": self.adapter_name,
            "frame_count": self.frame_count,
            "usable_frame_count": self.usable_frame_count,
            "lidar_ids": list(self.lidar_ids),
            "camera_ids": list(self.camera_ids),
            "reference_frame": self.reference_frame,
            "lidar_availability": [item.to_dict() for item in self.lidar_availability],
            "camera_availability": [item.to_dict() for item in self.camera_availability],
            "frame_cameras": {
                frame_id: list(camera_ids) for frame_id, camera_ids in self.frame_cameras
            },
            "calibration": {
                "sensor_states": dict(self.calibration_states),
                "camera_count": self.camera_calibration_count,
                "fingerprint": self.calibration_fingerprint,
            },
            "source_labels": {
                "frame_count": self.source_label_count,
                "object_count": self.source_object_count,
                "class_counts": dict(self.source_class_counts),
            },
            "working_labels": {
                "count": self.working_label_count,
                "revision_min": self.working_revision_min,
                "revision_max": self.working_revision_max,
            },
            "recovery_snapshot_count": self.recovery_snapshot_count,
            "issue_counts": {
                "info": self.info_count,
                "warning": self.warning_count,
                "error": self.error_count,
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


def _empty_report(root: Path, issue: PreflightIssue) -> PreflightReport:
    return PreflightReport(
        dataset_root=root,
        dataset_id=root.name,
        adapter_name="unknown",
        frame_count=0,
        usable_frame_count=0,
        lidar_ids=(),
        camera_ids=(),
        reference_frame="unknown",
        lidar_availability=(),
        camera_availability=(),
        frame_cameras=(),
        calibration_states=(),
        camera_calibration_count=0,
        calibration_fingerprint=None,
        source_label_count=0,
        source_object_count=0,
        source_class_counts=(),
        working_label_count=0,
        working_revision_min=None,
        working_revision_max=None,
        recovery_snapshot_count=0,
        issues=(issue,),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_format(adapter: object) -> str:
    return (
        "device_centric_json"
        if isinstance(adapter, DeviceCentricAdapter)
        else "waymo_frame_json"
    )


def validate_dataset(
    dataset_root: Path,
    *,
    class_mapping: Mapping[str, str] | None = None,
    workspace_root: Path | None = None,
    verify_images: bool = True,
) -> PreflightReport:
    """Read-only validation of dataset files, labels, calibration and work state."""
    root = Path(dataset_root).resolve()
    if not root.exists():
        return _empty_report(
            root,
            PreflightIssue("error", "dataset_root_missing", "데이터셋 폴더가 없습니다.", path=root),
        )
    if not root.is_dir():
        return _empty_report(
            root,
            PreflightIssue(
                "error", "dataset_root_not_directory", "데이터셋 경로가 폴더가 아닙니다.", path=root
            ),
        )
    try:
        adapter = open_dataset_adapter(root)
        index = adapter.scan()
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return _empty_report(
            root,
            PreflightIssue(
                "error",
                "adapter_open_failed",
                f"데이터셋 adapter를 열 수 없습니다: {type(exc).__name__}: {exc}",
                path=root,
            ),
        )

    issues: list[PreflightIssue] = []
    if index.frame_count <= 0:
        issues.append(PreflightIssue("error", "no_frames", "동기화된 프레임이 없습니다."))
    if not index.lidar_ids:
        issues.append(PreflightIssue("error", "no_lidar_sources", "LiDAR source가 없습니다."))
    if not index.camera_ids:
        issues.append(
            PreflightIssue("info", "no_camera_sources", "카메라 source가 없습니다. LiDAR 라벨링은 가능합니다.")
        )

    mapping = dict(class_mapping or {})
    importer = WaymoLabelImporter(mapping, source_format=_source_format(adapter))
    known_source_types = set(mapping)
    lidar_available: Counter[str] = Counter()
    camera_available: Counter[str] = Counter()
    frame_cameras: list[tuple[str, tuple[str, ...]]] = []
    calibration_states_seen: dict[str, set[str]] = defaultdict(set)
    source_class_counts: Counter[str] = Counter()
    unknown_source_types: Counter[str] = Counter()
    source_label_count = 0
    source_object_count = 0
    usable_frame_count = 0
    first_source: Any = None

    repository: LabelRepository | None
    try:
        repository = (
            LabelRepository.for_workspace(workspace_root, index.dataset_id)
            if workspace_root is not None
            else LabelRepository.for_sidecar(root, index.dataset_id)
        )
    except ValueError as exc:
        repository = None
        issues.append(
            PreflightIssue(
                "error", "invalid_dataset_id", f"작업 저장소를 만들 수 없는 dataset_id입니다: {exc}"
            )
        )

    working_label_count = 0
    working_revisions: list[int] = []
    for frame_id in index.frame_ids:
        try:
            source = adapter.load_source_frame(frame_id)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            issues.append(
                PreflightIssue(
                    "error",
                    "frame_metadata_error",
                    f"프레임 메타데이터를 읽을 수 없습니다: {type(exc).__name__}: {exc}",
                    frame_id=frame_id,
                )
            )
            continue
        if first_source is None:
            first_source = source
        frame_cameras.append((frame_id, tuple(sorted(source.image_paths))))

        raw_states = source.metadata.get("sensor_status", {})
        sensor_states = raw_states if isinstance(raw_states, Mapping) else {}
        frame_has_usable_lidar = False
        for sensor_id in index.lidar_ids:
            sensor_spec = adapter.point_spec_for(sensor_id)
            default_state = (
                "not_required"
                if source.point_spec.source_frame == index.reference_frame
                else "unknown"
            )
            state = str(sensor_states.get(sensor_id, default_state))
            calibration_states_seen[sensor_id].add(state)
            if state not in _USABLE_CALIBRATION_STATES:
                continue
            paths = source.point_cloud_paths.get(sensor_id, ())
            if not paths:
                issues.append(
                    PreflightIssue(
                        "error",
                        "missing_point_cloud",
                        "사용 가능한 LiDAR의 포인트 파일이 프레임에 없습니다.",
                        frame_id=frame_id,
                        sensor_id=sensor_id,
                    )
                )
                continue
            sensor_has_valid_file = False
            for path in paths:
                suffix = path.suffix.lower()
                if suffix not in _SUPPORTED_POINT_EXTENSIONS:
                    issues.append(
                        PreflightIssue(
                            "error",
                            "unsupported_point_extension",
                            f"지원하지 않는 포인트 확장자입니다: {suffix or '<없음>'}",
                            frame_id=frame_id,
                            sensor_id=sensor_id,
                            path=path,
                        )
                    )
                    continue
                if not path.is_file():
                    issues.append(
                        PreflightIssue(
                            "error",
                            "missing_point_cloud",
                            "포인트 클라우드 파일이 없습니다.",
                            frame_id=frame_id,
                            sensor_id=sensor_id,
                            path=path,
                        )
                    )
                    continue
                size = path.stat().st_size
                if size == 0:
                    issues.append(
                        PreflightIssue(
                            "error",
                            "empty_point_cloud",
                            "포인트 클라우드 파일이 비어 있습니다.",
                            frame_id=frame_id,
                            sensor_id=sensor_id,
                            path=path,
                        )
                    )
                    continue
                if suffix == ".bin" and size % sensor_spec.point_stride_bytes:
                    issues.append(
                        PreflightIssue(
                            "error",
                            "invalid_bin_stride",
                            f"BIN 크기 {size}가 stride {sensor_spec.point_stride_bytes}의 배수가 아닙니다.",
                            frame_id=frame_id,
                            sensor_id=sensor_id,
                            path=path,
                        )
                    )
                    continue
                sensor_has_valid_file = True
            if sensor_has_valid_file:
                lidar_available[sensor_id] += 1
                frame_has_usable_lidar = True
        if frame_has_usable_lidar:
            usable_frame_count += 1

        for camera_id in index.camera_ids:
            camera_path = source.image_paths.get(camera_id)
            if camera_path is None or not camera_path.is_file():
                issues.append(
                    PreflightIssue(
                        "warning",
                        "missing_camera_image",
                        "카메라 이미지가 없습니다.",
                        frame_id=frame_id,
                        sensor_id=camera_id,
                        path=camera_path,
                    )
                )
                continue
            camera_available[camera_id] += 1
            if verify_images:
                try:
                    with Image.open(camera_path) as image:
                        image.verify()
                except (OSError, UnidentifiedImageError) as exc:
                    issues.append(
                        PreflightIssue(
                            "warning",
                            "unreadable_camera_image",
                            f"카메라 이미지를 읽을 수 없습니다: {type(exc).__name__}: {exc}",
                            frame_id=frame_id,
                            sensor_id=camera_id,
                            path=camera_path,
                        )
                    )

        label_path = source.source_label_paths.get("laser")
        if label_path is not None:
            source_label_count += 1
            try:
                with label_path.open("r", encoding="utf-8") as stream:
                    raw_labels = json.load(stream)
                if not isinstance(raw_labels, list):
                    raise ValueError("source laser label root must be a list")
                imported_objects = importer.import_laser_objects(raw_labels)
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                AttributeError,
                json.JSONDecodeError,
            ) as exc:
                issues.append(
                    PreflightIssue(
                        "error",
                        "malformed_source_label",
                        f"원본 LiDAR 라벨을 읽을 수 없습니다: {type(exc).__name__}: {exc}",
                        frame_id=frame_id,
                        path=label_path,
                    )
                )
            else:
                source_object_count += len(imported_objects)
                source_class_counts.update(obj.class_name for obj in imported_objects)
                for item in raw_labels:
                    if isinstance(item, Mapping):
                        source_type = str(item.get("type", "TYPE_UNKNOWN"))
                        if source_type not in known_source_types:
                            unknown_source_types[source_type] += 1

        if repository is not None and repository.exists(frame_id):
            working_label_count += 1
            try:
                working = repository.load(frame_id)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                issues.append(
                    PreflightIssue(
                        "error",
                        "malformed_working_label",
                        f"작업 라벨을 읽을 수 없습니다: {type(exc).__name__}: {exc}",
                        frame_id=frame_id,
                        path=repository.path_for(frame_id),
                    )
                )
            else:
                working_revisions.append(working.revision)

    if source_label_count == 0:
        issues.append(
            PreflightIssue(
                "info", "source_labels_absent", "원본 LiDAR 라벨이 없습니다. 빈 라벨부터 작업할 수 있습니다."
            )
        )
    elif source_label_count < index.frame_count:
        issues.append(
            PreflightIssue(
                "info",
                "source_labels_partial",
                f"원본 LiDAR 라벨이 {source_label_count}/{index.frame_count} 프레임에 있습니다.",
            )
        )
    for source_type, count in sorted(unknown_source_types.items()):
        issues.append(
            PreflightIssue(
                "warning",
                "unknown_source_class",
                f"매핑되지 않은 원본 클래스 {source_type!r} 객체가 {count}개 있어 Unknown으로 처리됩니다.",
            )
        )

    if index.frame_count and usable_frame_count == 0:
        issues.append(
            PreflightIssue(
                "error",
                "no_usable_lidar_frames",
                "검증을 통과한 LiDAR 포인트 파일이 있는 프레임이 없습니다.",
            )
        )

    calibration_states: list[tuple[str, str]] = []
    for sensor_id in index.lidar_ids:
        states = calibration_states_seen.get(sensor_id) or {"unknown"}
        state = next(iter(states)) if len(states) == 1 else "mixed:" + ",".join(sorted(states))
        calibration_states.append((sensor_id, state))
        if state in {"missing", "invalid", "unknown"}:
            issues.append(
                PreflightIssue(
                    "warning",
                    f"calibration_{state}",
                    f"LiDAR calibration 상태가 {state}입니다.",
                    sensor_id=sensor_id,
                )
            )

    calibration_fingerprint: str | None = None
    calibration_path: Path | None = None
    if first_source is not None:
        relative = first_source.metadata.get("calibration_path")
        if relative:
            calibration_path = root / str(relative)
    if calibration_path is None and (root / "segment.json").is_file():
        calibration_path = root / "segment.json"
    if calibration_path is not None and calibration_path.is_file():
        try:
            calibration_fingerprint = _sha256(calibration_path)
        except OSError as exc:
            issues.append(
                PreflightIssue(
                    "warning",
                    "calibration_fingerprint_failed",
                    f"보정 fingerprint를 계산할 수 없습니다: {exc}",
                    path=calibration_path,
                )
            )

    recovery_snapshot_count = 0
    if repository is not None:
        recovery_store = RecoveryStore(repository.annotation_dir)
        if recovery_store.recovery_dir.is_dir():
            for path in recovery_store.recovery_dir.glob("*.recovery.json"):
                recovery_snapshot_count += 1
                frame_id = path.name[: -len(".recovery.json")]
                result = recovery_store.inspect(frame_id)
                if result.error is not None:
                    issues.append(
                        PreflightIssue(
                            "warning",
                            "malformed_recovery_snapshot",
                            f"복구 snapshot을 읽을 수 없습니다: {result.error}",
                            frame_id=frame_id,
                            path=path,
                        )
                    )

    return PreflightReport(
        dataset_root=root,
        dataset_id=index.dataset_id,
        adapter_name=index.adapter_name,
        frame_count=index.frame_count,
        usable_frame_count=usable_frame_count,
        lidar_ids=index.lidar_ids,
        camera_ids=index.camera_ids,
        reference_frame=index.reference_frame,
        lidar_availability=tuple(
            SensorAvailability(
                sensor_id,
                lidar_available[sensor_id],
                index.frame_count - lidar_available[sensor_id],
            )
            for sensor_id in index.lidar_ids
        ),
        camera_availability=tuple(
            SensorAvailability(
                sensor_id,
                camera_available[sensor_id],
                index.frame_count - camera_available[sensor_id],
            )
            for sensor_id in index.camera_ids
        ),
        frame_cameras=tuple(frame_cameras),
        calibration_states=tuple(calibration_states),
        camera_calibration_count=int(getattr(adapter, "camera_calibration_count", 0)),
        calibration_fingerprint=calibration_fingerprint,
        source_label_count=source_label_count,
        source_object_count=source_object_count,
        source_class_counts=tuple(sorted(source_class_counts.items())),
        working_label_count=working_label_count,
        working_revision_min=min(working_revisions) if working_revisions else None,
        working_revision_max=max(working_revisions) if working_revisions else None,
        recovery_snapshot_count=recovery_snapshot_count,
        issues=tuple(issues),
    )


@dataclass(frozen=True, slots=True)
class DatasetPreflight:
    dataset_root: Path
    dataset_id: str
    adapter_name: str
    frame_count: int
    lidar_ids: tuple[str, ...]
    camera_ids: tuple[str, ...]
    point_columns: tuple[str, ...]
    source_frame: str
    source_label_layers: tuple[str, ...]
    camera_calibration_count: int
    working_directory: Path
    working_directory_writable: bool
    write_error: str | None
    warnings: tuple[str, ...]

    def summary_text(self) -> str:
        lidar_text = ", ".join(self.lidar_ids) or "없음"
        camera_text = ", ".join(self.camera_ids) or "없음"
        labels_text = ", ".join(self.source_label_layers) or "없음"
        write_text = "사용 가능" if self.working_directory_writable else "사용 불가"
        calibration_text = (
            "LiDAR 재적용 불필요"
            if self.source_frame == "vehicle"
            else "LiDAR calibration 확인 필요"
        )
        lines = [
            f"데이터셋: {self.dataset_id}",
            f"형식: {self.adapter_name}",
            f"프레임: {self.frame_count}개",
            f"LiDAR: {lidar_text}",
            f"카메라: {camera_text}",
            f"포인트 열: {', '.join(self.point_columns)}",
            f"원본 좌표계: {self.source_frame} ({calibration_text})",
            f"원본 라벨: {labels_text}",
            f"카메라 보정: {self.camera_calibration_count}개",
            f"작업 저장 폴더: {self.working_directory}",
            f"저장 가능 여부: {write_text}",
        ]
        if self.write_error:
            lines.append(f"저장 확인 오류: {self.write_error}")
        if self.warnings:
            lines.append("경고:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        return "\n".join(lines)


def probe_writable_directory(directory: Path) -> tuple[bool, str | None]:
    """Create and remove a probe file in the exact working-label directory."""
    directory = Path(directory)
    probe = directory / f".write-probe-{uuid4().hex}.tmp"
    created_directories: list[Path] = []
    cursor = directory
    while not cursor.exists() and cursor != cursor.parent:
        created_directories.append(cursor)
        cursor = cursor.parent
    result: tuple[bool, str | None]
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with probe.open("x", encoding="utf-8") as stream:
            stream.write("LiDAR Label Tool write probe\n")
            stream.flush()
        probe.unlink()
    except OSError as exc:
        try:
            probe.unlink()
        except OSError:
            pass
        result = (False, f"{type(exc).__name__}: {exc}")
    else:
        result = (True, None)
    finally:
        for created in created_directories:
            try:
                created.rmdir()
            except OSError:
                pass
    return result


def inspect_dataset(
    dataset_root: Path,
    *,
    workspace_root: Path | None = None,
    probe_write: bool = True,
) -> DatasetPreflight:
    root = Path(dataset_root).resolve()
    adapter = open_dataset_adapter(root)
    index = adapter.scan()
    source = adapter.load_source_frame(index.frame_ids[0])
    repository = (
        LabelRepository.for_workspace(workspace_root, index.dataset_id)
        if workspace_root is not None
        else LabelRepository.for_sidecar(root, index.dataset_id)
    )
    writable, write_error = (
        probe_writable_directory(repository.annotation_dir)
        if probe_write
        else (True, None)
    )
    warnings: list[str] = []
    missing_lidars = sorted(set(index.lidar_ids) - set(source.point_cloud_paths))
    missing_cameras = sorted(set(index.camera_ids) - set(source.image_paths))
    if missing_lidars:
        warnings.append(f"첫 프레임 LiDAR 누락: {', '.join(missing_lidars)}")
    if missing_cameras:
        warnings.append(f"첫 프레임 카메라 누락: {', '.join(missing_cameras)}")
    if not source.source_label_paths:
        warnings.append("첫 프레임에 원본 라벨이 없습니다.")
    return DatasetPreflight(
        dataset_root=root,
        dataset_id=index.dataset_id,
        adapter_name=index.adapter_name,
        frame_count=index.frame_count,
        lidar_ids=index.lidar_ids,
        camera_ids=index.camera_ids,
        point_columns=index.point_spec.columns,
        source_frame=index.point_spec.source_frame,
        source_label_layers=tuple(sorted(source.source_label_paths)),
        camera_calibration_count=int(getattr(adapter, "camera_calibration_count", 0)),
        working_directory=repository.annotation_dir,
        working_directory_writable=writable,
        write_error=write_error,
        warnings=tuple(warnings),
    )

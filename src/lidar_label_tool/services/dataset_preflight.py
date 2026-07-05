from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.json_repository import LabelRepository


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

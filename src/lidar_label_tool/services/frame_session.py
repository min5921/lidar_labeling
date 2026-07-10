from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.io.dataset import DatasetAdapter, SourceFrameData
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter, sha256_file


@dataclass(frozen=True, slots=True)
class LabelContextIssue:
    code: str
    message: str


def _safe_dataset_path(dataset_root: Path, relative_path: str) -> Path:
    root = dataset_root.resolve()
    candidate = (root / Path(relative_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"source path escapes dataset root: {relative_path}") from exc
    return candidate


def _calibration_path(source: SourceFrameData) -> Path:
    relative = source.metadata.get("calibration_path")
    if relative:
        return _safe_dataset_path(source.dataset_root, str(relative))
    return source.dataset_root / "segment.json"


def _current_source_fingerprints(source: SourceFrameData) -> dict[str, str]:
    return {
        path.relative_to(source.dataset_root).as_posix(): sha256_file(path)
        for path in source.source_label_paths.values()
    }


def _current_calibration_fingerprint(source: SourceFrameData) -> str | None:
    path = _calibration_path(source)
    return sha256_file(path) if path.is_file() else None


def compare_label_context(
    label: FrameLabel, source: SourceFrameData
) -> tuple[LabelContextIssue, ...]:
    """Compare saved source/calibration fingerprints with current dataset files."""
    issues: list[LabelContextIssue] = []
    raw_fingerprints = label.provenance.get("source_fingerprints", {})
    expected_sources = (
        raw_fingerprints if isinstance(raw_fingerprints, Mapping) else {}
    )
    for relative_path, expected in expected_sources.items():
        try:
            path = _safe_dataset_path(source.dataset_root, str(relative_path))
            if not path.is_file():
                issues.append(
                    LabelContextIssue(
                        "source_missing",
                        f"원본 라벨 파일이 없어졌습니다: {relative_path}",
                    )
                )
                continue
            current = sha256_file(path)
        except (OSError, ValueError) as exc:
            issues.append(
                LabelContextIssue(
                    "source_fingerprint_unreadable",
                    f"원본 라벨 fingerprint를 확인할 수 없습니다: {relative_path} ({exc})",
                )
            )
            continue
        if current != str(expected):
            issues.append(
                LabelContextIssue(
                    "source_changed",
                    f"작업 시작 후 원본 라벨이 변경되었습니다: {relative_path}",
                )
            )

    expected_calibration = label.calibration_state.get("fingerprint")
    try:
        current_calibration = _current_calibration_fingerprint(source)
    except (OSError, ValueError) as exc:
        issues.append(
            LabelContextIssue(
                "calibration_fingerprint_unreadable",
                f"현재 calibration fingerprint를 확인할 수 없습니다: {exc}",
            )
        )
    else:
        if expected_calibration != current_calibration:
            issues.append(
                LabelContextIssue(
                    "calibration_changed",
                    "작업 라벨을 만든 뒤 calibration이 변경되었습니다. 투영과 정렬을 재검토하세요.",
                )
            )
    return tuple(issues)


def refresh_label_context(label: FrameLabel, source: SourceFrameData) -> FrameLabel:
    """Acknowledge current source/calibration files after explicit user confirmation."""
    provenance: dict[str, Any] = dict(label.provenance)
    provenance["source_fingerprints"] = _current_source_fingerprints(source)
    calibration_state: dict[str, Any] = dict(label.calibration_state)
    calibration_state["fingerprint"] = _current_calibration_fingerprint(source)
    return replace(
        label,
        provenance=provenance,
        calibration_state=calibration_state,
    )


@dataclass(frozen=True, slots=True)
class OpenedFrame:
    source: SourceFrameData
    label: FrameLabel
    label_origin: str
    context_issues: tuple[LabelContextIssue, ...] = ()


class FrameSessionService:
    def __init__(
        self,
        adapter: DatasetAdapter,
        importer: WaymoLabelImporter,
        repository: LabelRepository | None = None,
    ) -> None:
        self.adapter = adapter
        self.importer = importer
        self.repository = repository

    def open_frame(self, frame_id: str) -> OpenedFrame:
        source = self.adapter.load_source_frame(frame_id)
        if self.repository is not None and self.repository.exists(frame_id):
            label = self.repository.load(frame_id)
            return OpenedFrame(
                source,
                label,
                "working",
                compare_label_context(label, source),
            )
        return OpenedFrame(source, self.importer.import_laser_labels(source), "source")

    def save(self, label: FrameLabel) -> FrameLabel:
        if self.repository is None:
            raise RuntimeError("no working label repository configured")
        return self.repository.save(label)

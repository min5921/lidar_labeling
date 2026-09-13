from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Iterable, Mapping

from lidar_label_tool.domain.labels import FRAME_STATUSES, FrameLabel
from lidar_label_tool.io.dataset import SourceFrameData
from lidar_label_tool.io.labels.repository_factory import WorkingLabelRepository
from lidar_label_tool.services.background_task import TaskControl
from lidar_label_tool.services.frame_session import compare_label_context


REVIEW_STATUS_TEXT = {
    "unvisited": "미방문", "in_progress": "작업 중", "reviewed": "검토 완료",
    "skipped": "건너뜀", "error": "오류", "unknown": "미확인",
}


@dataclass(frozen=True, slots=True)
class FrameReviewEntry:
    frame_id: str
    status: str
    error: str | None = None
    needs_review: bool = False


@dataclass(frozen=True, slots=True)
class FrameReviewScan:
    entries: tuple[FrameReviewEntry, ...]


def set_frame_review_status(label: FrameLabel, status: str) -> FrameLabel:
    """An explicit review command only changes status; ordinary history/save owns persistence."""
    if status not in FRAME_STATUSES:
        raise ValueError(f"unsupported frame status: {status}")
    return replace(label, frame_status=status)


def require_re_review(previous: FrameLabel, edited: FrameLabel) -> FrameLabel:
    """Object edits invalidate completion; viewing or marking a status alone does not."""
    if previous.objects != edited.objects:
        return replace(edited, frame_status="in_progress")
    return edited


def scan_frame_review(
    repository: WorkingLabelRepository,
    frame_ids: Iterable[str],
    control: TaskControl | None = None,
    source_reader: Callable[[str], SourceFrameData] | None = None,
) -> FrameReviewScan:
    """Read a profile-scoped repository, never write or hide a corrupt working label.

    Callers must supply a separate reader, not the live editor repository: load()
    establishes a save fingerprint baseline and must not rebase an open edit.
    Full repository validation includes label identity, schema and frozen binding.
    Cancellation is checked between frames; each label is validated atomically.
    """
    ordered = tuple(frame_ids)
    entries: list[FrameReviewEntry] = []
    task = control or TaskControl()
    for position, frame_id in enumerate(ordered):
        task.check_cancelled()
        try:
            label = repository.load(frame_id) if repository.exists(frame_id) else None
            status = label.frame_status if label is not None else "unvisited"
            issues = (
                compare_label_context(label, source_reader(frame_id))
                if label is not None and source_reader is not None and status in {"reviewed", "skipped"}
                else ()
            )
            entry = FrameReviewEntry(
                frame_id, "in_progress" if issues else status,
                "\n".join(issue.message for issue in issues) if issues else None,
                needs_review=bool(issues),
            )
        except (OSError, ValueError) as exc:
            entry = FrameReviewEntry(frame_id, "error", f"{type(exc).__name__}: {exc}")
        entries.append(entry)
        task.report("frame_review", position + 1, len(ordered), f"프레임 상태 확인: {frame_id}")
    task.check_cancelled()
    return FrameReviewScan(tuple(entries))


def next_unreviewed_frame(
    frame_ids: Iterable[str],
    current_frame_id: str,
    entries: Mapping[str, FrameReviewEntry],
) -> str | None:
    """Search once in frozen order, after current then wrap; errors are never skipped.

    Reviewed/skipped are terminal only until another explicit edit. Unknown entries
    and read errors stay review candidates, so missing/bad labels cannot disappear.
    """
    ordered = tuple(frame_ids)
    position = ordered.index(current_frame_id)
    candidates = ordered[position + 1:] + ordered[:position]
    for frame_id in candidates:
        entry = entries.get(frame_id)
        if entry is None or entry.status not in {"reviewed", "skipped"}:
            return frame_id
    return None


def visible_review_frame(entry: FrameReviewEntry | None, selected_filter: str) -> bool:
    # Even a narrow filter must leave corrupt labels visible for intervention.
    if entry is None or entry.status in {"unknown", "error"}:
        return True
    if selected_filter == "all":
        return True
    if selected_filter == "unreviewed":
        return entry.status not in {"reviewed", "skipped"}
    return entry.status == selected_filter

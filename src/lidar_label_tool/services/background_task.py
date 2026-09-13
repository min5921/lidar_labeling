from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event


class TaskCancelled(RuntimeError):
    """Cooperative cancellation acknowledged at a safe service boundary."""


@dataclass(frozen=True, slots=True)
class TaskProgress:
    stage: str
    completed: int
    total: int
    message: str


class TaskControl:
    """Qt-free cancellation and progress; never interrupts atomic commit midway."""

    def __init__(self, progress: Callable[[TaskProgress], None] | None = None) -> None:
        self._cancelled = Event()
        self._progress = progress

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise TaskCancelled("작업이 취소되었습니다.")

    def report(self, stage: str, completed: int, total: int, message: str) -> None:
        self.check_cancelled()
        if self._progress is not None:
            self._progress(TaskProgress(stage, completed, total, message))
        self.check_cancelled()

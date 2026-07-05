from __future__ import annotations

from dataclasses import dataclass, field

from lidar_label_tool.domain.labels import FrameLabel


@dataclass(slots=True)
class AnnotationHistory:
    current: FrameLabel
    baseline: FrameLabel
    limit: int = 100
    _undo: list[FrameLabel] = field(default_factory=list)
    _redo: list[FrameLabel] = field(default_factory=list)

    @classmethod
    def start(cls, label: FrameLabel, limit: int = 100) -> AnnotationHistory:
        return cls(current=label, baseline=label, limit=limit)

    @property
    def dirty(self) -> bool:
        return self.current != self.baseline

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def apply(self, label: FrameLabel) -> bool:
        if label == self.current:
            return False
        self._undo.append(self.current)
        if len(self._undo) > self.limit:
            del self._undo[0]
        self.current = label
        self._redo.clear()
        return True

    def undo(self) -> FrameLabel:
        if not self._undo:
            return self.current
        self._redo.append(self.current)
        self.current = self._undo.pop()
        return self.current

    def redo(self) -> FrameLabel:
        if not self._redo:
            return self.current
        self._undo.append(self.current)
        self.current = self._redo.pop()
        return self.current

    def mark_saved(self, label: FrameLabel) -> None:
        self.current = label
        self.baseline = label


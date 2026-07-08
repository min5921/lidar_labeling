from __future__ import annotations

from collections.abc import Collection

from lidar_label_tool.exporters.base import LabelExporter
from lidar_label_tool.exporters.centerpoint_intermediate_json import (
    CenterPointIntermediateJsonExporter,
)
from lidar_label_tool.exporters.lidar_label_json import LidarLabelJsonExporter


class ExporterRegistry:
    """Instance-scoped exporter registry; GUI code can receive one via composition."""

    def __init__(self) -> None:
        self._exporters: dict[str, LabelExporter] = {}

    def register(self, exporter: LabelExporter) -> None:
        if not exporter.name:
            raise ValueError("exporter name must not be empty")
        if exporter.name in self._exporters:
            raise ValueError(f"exporter already registered: {exporter.name}")
        self._exporters[exporter.name] = exporter

    def get(self, name: str) -> LabelExporter:
        try:
            return self._exporters[name]
        except KeyError as exc:
            raise KeyError(f"unknown exporter: {name}") from exc

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._exporters))


def create_default_registry(
    allowed_classes: Collection[str] | None = None,
) -> ExporterRegistry:
    registry = ExporterRegistry()
    registry.register(LidarLabelJsonExporter(allowed_classes))
    registry.register(CenterPointIntermediateJsonExporter(allowed_classes))
    return registry

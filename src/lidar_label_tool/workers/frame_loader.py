from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from lidar_label_tool.domain.labels import FrameLabel
from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.io.dataset import DatasetAdapter, SourceFrameData
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import FrameSessionService


@dataclass(frozen=True, slots=True)
class FrameLoadPayload:
    source: SourceFrameData
    label: FrameLabel
    label_origin: str
    clouds: Mapping[str, tuple[PointCloudData, ...]]
    reference_layers: Mapping[str, Any]
    sensor_errors: Mapping[str, str] = field(default_factory=dict)
    reference_layer_errors: Mapping[str, str] = field(default_factory=dict)


def _error_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def load_frame_payload(
    adapter: DatasetAdapter,
    importer: WaymoLabelImporter,
    frame_id: str,
    repository: LabelRepository | None = None,
) -> FrameLoadPayload:
    opened = FrameSessionService(adapter, importer, repository).open_frame(frame_id)
    clouds: dict[str, tuple[PointCloudData, ...]] = {}
    sensor_errors: dict[str, str] = {}
    for sensor, paths in opened.source.point_cloud_paths.items():
        loaded: list[PointCloudData] = []
        for index in range(len(paths)):
            return_id = str(index + 1)
            try:
                cloud = adapter.load_cloud_from_source(
                    opened.source, sensor, return_id
                )
            except Exception as exc:
                sensor_errors[f"{sensor}:return{return_id}"] = _error_text(exc)
            else:
                loaded.append(cloud)
        if loaded:
            clouds[sensor] = tuple(loaded)

    reference_layers: dict[str, Any] = {}
    reference_layer_errors: dict[str, str] = {}
    for layer_name in ("camera", "projected_lidar"):
        if layer_name not in opened.source.source_label_paths:
            continue
        try:
            reference_layers[layer_name] = importer.load_reference_layer(
                opened.source, layer_name
            )
        except Exception as exc:
            reference_layer_errors[layer_name] = _error_text(exc)

    usable_cloud = any(
        cloud.point_count > 0 for sensor_clouds in clouds.values() for cloud in sensor_clouds
    )
    usable_non_lidar = bool(
        opened.source.image_paths
        or opened.label.objects
        or "laser" in opened.source.source_label_paths
        or reference_layers
    )
    if not usable_cloud and not usable_non_lidar:
        failures = "; ".join(
            f"{name}: {message}" for name, message in sensor_errors.items()
        ) or "no LiDAR source was found"
        raise RuntimeError(
            f"frame {frame_id} has no usable LiDAR cloud, image, or label data; "
            f"{failures}"
        )

    return FrameLoadPayload(
        source=opened.source,
        label=opened.label,
        label_origin=opened.label_origin,
        clouds=clouds,
        reference_layers=reference_layers,
        sensor_errors=sensor_errors,
        reference_layer_errors=reference_layer_errors,
    )

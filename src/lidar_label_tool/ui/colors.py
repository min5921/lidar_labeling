from __future__ import annotations

from typing import Final

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData


SENSOR_COLORS: Final[dict[str, tuple[float, float, float, float]]] = {
    "TOP": (0.92, 0.92, 0.92, 0.85),
    "FRONT": (1.0, 0.25, 0.2, 0.85),
    "REAR": (0.2, 0.55, 1.0, 0.85),
    "SIDE_LEFT": (0.2, 0.9, 0.45, 0.85),
    "SIDE_RIGHT": (0.95, 0.35, 0.9, 0.85),
}

CLASS_COLORS: Final[dict[str, tuple[int, int, int]]] = {
    "Car": (0, 208, 132),
    "Pedestrian": (255, 176, 32),
    "Cyclist": (76, 154, 255),
    "Sign": (199, 125, 255),
    "Unknown": (160, 160, 160),
}


def sensor_color(sensor_id: str) -> tuple[float, float, float, float]:
    return SENSOR_COLORS.get(sensor_id, (0.75, 0.75, 0.75, 0.8))


def class_color(class_name: str) -> tuple[int, int, int]:
    return CLASS_COLORS.get(class_name, CLASS_COLORS["Unknown"])


_VIRIDIS = np.array(
    [
        [0.267, 0.005, 0.329],
        [0.230, 0.322, 0.546],
        [0.128, 0.567, 0.551],
        [0.369, 0.789, 0.383],
        [0.993, 0.906, 0.144],
    ],
    dtype=np.float32,
)

_TURBO = np.array(
    [
        [0.190, 0.072, 0.232],
        [0.160, 0.478, 0.858],
        [0.138, 0.808, 0.588],
        [0.638, 0.991, 0.236],
        [0.985, 0.556, 0.114],
        [0.480, 0.016, 0.011],
    ],
    dtype=np.float32,
)


def _hex_rgba(value: str, alpha: float = 0.9) -> tuple[float, float, float, float]:
    text = value.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"invalid RGB color: {value}")
    return (
        int(text[0:2], 16) / 255.0,
        int(text[2:4], 16) / 255.0,
        int(text[4:6], 16) / 255.0,
        alpha,
    )


def _normalized(values: np.ndarray, *, logarithmic: bool = False) -> np.ndarray:
    values = values.astype(np.float32, copy=False)
    if logarithmic:
        values = np.log1p(np.clip(values, 0.0, None))
    finite = np.isfinite(values)
    result = np.zeros(values.shape, dtype=np.float32)
    if not finite.any():
        return result
    low, high = np.percentile(values[finite], [2.0, 98.0])
    if high <= low:
        return result
    result[finite] = np.clip((values[finite] - low) / (high - low), 0.0, 1.0)
    return result


def _gradient(values: np.ndarray, stops: np.ndarray) -> np.ndarray:
    scaled = values * (len(stops) - 1)
    lower = np.floor(scaled).astype(np.int32)
    upper = np.minimum(lower + 1, len(stops) - 1)
    weight = (scaled - lower)[:, None]
    return stops[lower] * (1.0 - weight) + stops[upper] * weight


def point_rgba(
    cloud: PointCloudData,
    mode: str,
    uniform_color: str = "#E8E8E8",
) -> np.ndarray:
    """Return float RGBA colors with shape [N, 4]."""
    if mode == "sensor":
        rgba = sensor_color(cloud.sensor_id)
        return np.tile(np.asarray(rgba, dtype=np.float32), (cloud.point_count, 1))
    if mode == "uniform":
        rgba = _hex_rgba(uniform_color)
        return np.tile(np.asarray(rgba, dtype=np.float32), (cloud.point_count, 1))
    if mode == "height":
        normalized = _normalized(cloud.xyz[:, 2])
        rgb = _gradient(normalized, _VIRIDIS)
    elif mode == "intensity":
        intensity = cloud.attributes.get("intensity")
        if intensity is None:
            return point_rgba(cloud, "uniform", uniform_color)
        normalized = _normalized(intensity, logarithmic=True)
        rgb = _gradient(normalized, _TURBO)
    else:
        raise ValueError(f"unknown point color mode: {mode}")
    alpha = np.full((cloud.point_count, 1), 0.9, dtype=np.float32)
    return np.ascontiguousarray(np.hstack((rgb, alpha)), dtype=np.float32)

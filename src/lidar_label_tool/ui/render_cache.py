from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
import weakref
from typing import Iterable

import numpy as np
from numpy.typing import NDArray

from lidar_label_tool.domain.point_cloud import PointCloudData
from lidar_label_tool.ui.colors import point_rgba


@dataclass(frozen=True, slots=True)
class RenderCloudArrays:
    """Display-only arrays; neither array shares writable data with the source cloud."""

    xyz: NDArray[np.float32]
    rgba: NDArray[np.float32]

    @property
    def point_count(self) -> int:
        return int(self.xyz.shape[0])

    @property
    def nbytes(self) -> int:
        return int(self.xyz.nbytes + self.rgba.nbytes)


@dataclass(frozen=True, slots=True)
class RenderCloudBatch:
    clouds: tuple[RenderCloudArrays, ...]
    token: tuple[object, ...]
    loaded_point_count: int
    rendered_point_count: int


@dataclass(slots=True)
class _CacheEntry:
    source_xyz: weakref.ReferenceType[NDArray[np.float32]]
    arrays: RenderCloudArrays


class PointCloudRenderCache:
    """Small LRU for downsampled positions and colors used only for display."""

    def __init__(self, *, max_cache_mb: int = 256, max_items: int = 64) -> None:
        if max_cache_mb <= 0 or max_items <= 0:
            raise ValueError("render cache limits must be positive")
        self.max_bytes = int(max_cache_mb * 1024 * 1024)
        self.max_items = max_items
        self._entries: OrderedDict[tuple[object, ...], _CacheEntry] = OrderedDict()
        self._bytes = 0

    @property
    def item_count(self) -> int:
        return len(self._entries)

    @property
    def size_bytes(self) -> int:
        return self._bytes

    def clear(self) -> None:
        self._entries.clear()
        self._bytes = 0

    def prepare(
        self,
        clouds: Iterable[PointCloudData],
        *,
        max_points: int,
        color_mode: str,
        uniform_color: str,
    ) -> RenderCloudBatch:
        if max_points <= 0:
            raise ValueError("max_points must be positive")
        cloud_tuple = tuple(clouds)
        total = sum(cloud.point_count for cloud in cloud_tuple)
        stride = max(1, math.ceil(total / max_points)) if total else 1
        prepared: list[RenderCloudArrays] = []
        keys: list[tuple[object, ...]] = []
        for cloud in cloud_tuple:
            intensity = cloud.attributes.get("intensity")
            key = (
                id(cloud.xyz),
                id(intensity) if intensity is not None else None,
                cloud.point_count,
                str(cloud.source_path),
                cloud.sensor_id,
                cloud.return_id,
                max_points,
                stride,
                color_mode,
                uniform_color,
            )
            arrays = self._get(key, cloud)
            if arrays is None:
                arrays = self._build(cloud, stride, color_mode, uniform_color)
                self._put(key, cloud, arrays)
            prepared.append(arrays)
            keys.append(key)
        return RenderCloudBatch(
            clouds=tuple(prepared),
            token=tuple(keys),
            loaded_point_count=total,
            rendered_point_count=sum(item.point_count for item in prepared),
        )

    def _get(
        self, key: tuple[object, ...], cloud: PointCloudData
    ) -> RenderCloudArrays | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.source_xyz() is not cloud.xyz:
            self._remove(key)
            return None
        self._entries.move_to_end(key)
        return entry.arrays

    @staticmethod
    def _build(
        cloud: PointCloudData,
        stride: int,
        color_mode: str,
        uniform_color: str,
    ) -> RenderCloudArrays:
        xyz = np.array(cloud.xyz[::stride], dtype=np.float32, order="C", copy=True)
        rgba = np.array(
            point_rgba(cloud, color_mode, uniform_color)[::stride],
            dtype=np.float32,
            order="C",
            copy=True,
        )
        xyz.flags.writeable = False
        rgba.flags.writeable = False
        return RenderCloudArrays(xyz=xyz, rgba=rgba)

    def _put(
        self,
        key: tuple[object, ...],
        cloud: PointCloudData,
        arrays: RenderCloudArrays,
    ) -> None:
        if arrays.nbytes > self.max_bytes:
            return
        self._entries[key] = _CacheEntry(weakref.ref(cloud.xyz), arrays)
        self._bytes += arrays.nbytes
        while len(self._entries) > self.max_items or self._bytes > self.max_bytes:
            oldest = next(iter(self._entries))
            self._remove(oldest)

    def _remove(self, key: tuple[object, ...]) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= entry.arrays.nbytes

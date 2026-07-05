from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class PointCloudSpec:
    columns: tuple[str, ...]
    source_frame: str
    dtype: str = "float32"
    byte_order: str = "little-endian"

    def __post_init__(self) -> None:
        if self.dtype != "float32":
            raise ValueError(f"unsupported point dtype: {self.dtype}")
        if self.byte_order not in {"little-endian", "big-endian"}:
            raise ValueError(f"unsupported byte order: {self.byte_order}")
        if len(self.columns) < 3 or not {"x", "y", "z"}.issubset(self.columns):
            raise ValueError("point columns must include x, y and z")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("point column names must be unique")

    @property
    def numpy_dtype(self) -> np.dtype[np.float32]:
        prefix = "<" if self.byte_order == "little-endian" else ">"
        return np.dtype(f"{prefix}f4")

    @property
    def point_stride_bytes(self) -> int:
        return 4 * len(self.columns)


@dataclass(frozen=True, slots=True)
class PointCloudData:
    xyz: NDArray[np.float32]
    attributes: Mapping[str, NDArray[np.float32]]
    sensor_id: str
    return_id: str
    source_frame: str
    source_path: Path
    invalid_point_count: int = 0
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.xyz.ndim != 2 or self.xyz.shape[1] != 3:
            raise ValueError("xyz must have shape [N, 3]")
        size = self.xyz.shape[0]
        for name, values in self.attributes.items():
            if values.ndim != 1 or values.shape[0] != size:
                raise ValueError(f"attribute {name!r} must have shape [N]")

    @property
    def point_count(self) -> int:
        return int(self.xyz.shape[0])


from __future__ import annotations

from pathlib import Path

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData, PointCloudSpec


class BinaryPointCloudLoader:
    """Load a manifest-described dense float32 point array."""

    def can_load(self, path: Path, spec: PointCloudSpec) -> bool:
        return path.suffix.lower() == ".bin" and spec.dtype == "float32"

    def load(
        self,
        path: Path,
        spec: PointCloudSpec,
        *,
        sensor_id: str,
        return_id: str,
    ) -> PointCloudData:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        size = path.stat().st_size
        if size % spec.point_stride_bytes != 0:
            raise ValueError(
                f"{path} size {size} is not divisible by point stride "
                f"{spec.point_stride_bytes}"
            )
        raw = np.fromfile(path, dtype=spec.numpy_dtype)
        if raw.size == 0:
            matrix = raw.reshape(0, len(spec.columns))
        else:
            matrix = raw.reshape(-1, len(spec.columns))

        indices = {name: index for index, name in enumerate(spec.columns)}
        xyz = matrix[:, [indices["x"], indices["y"], indices["z"]]].astype(
            np.float32, copy=False
        )
        valid = np.isfinite(xyz).all(axis=1)
        invalid_count = int((~valid).sum())
        if invalid_count:
            xyz = xyz[valid]

        attributes: dict[str, np.ndarray] = {}
        for name, index in indices.items():
            if name in {"x", "y", "z"}:
                continue
            values = matrix[:, index].astype(np.float32, copy=False)
            attributes[name] = values[valid] if invalid_count else values

        return PointCloudData(
            xyz=np.ascontiguousarray(xyz),
            attributes=attributes,
            sensor_id=sensor_id,
            return_id=return_id,
            source_frame=spec.source_frame,
            source_path=path,
            invalid_point_count=invalid_count,
            metadata={"raw_point_count": int(matrix.shape[0]), "columns": spec.columns},
        )


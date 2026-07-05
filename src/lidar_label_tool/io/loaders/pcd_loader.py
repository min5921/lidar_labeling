from __future__ import annotations

import io
from pathlib import Path

import numpy as np

from lidar_label_tool.domain.point_cloud import PointCloudData, PointCloudSpec


class PcdPointCloudLoader:
    """Load PCD v0.7 ASCII or uncompressed binary point clouds."""

    def can_load(self, path: Path, spec: PointCloudSpec) -> bool:
        return Path(path).suffix.lower() == ".pcd" and spec.dtype == "float32"

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
        header, data_offset = self._read_header(path)
        fields = tuple(header.get("FIELDS", ()))
        if not fields or not {"x", "y", "z"}.issubset(fields):
            raise ValueError(f"PCD fields must include x, y and z: {path}")
        missing = set(spec.columns) - set(fields)
        if missing:
            raise ValueError(f"PCD is missing declared columns {sorted(missing)}: {path}")
        counts = tuple(int(value) for value in header.get("COUNT", ["1"] * len(fields)))
        if len(counts) != len(fields) or any(value != 1 for value in counts):
            raise ValueError("PCD COUNT values other than 1 are not supported")
        mode = str(header.get("DATA", [""])[0]).lower()
        points = int(header.get("POINTS", ["0"])[0])
        if mode == "ascii":
            with path.open("rb") as stream:
                stream.seek(data_offset)
                payload = stream.read()
            matrix = np.loadtxt(io.BytesIO(payload), dtype=np.float32, ndmin=2)
            if matrix.size == 0:
                matrix = np.empty((0, len(fields)), dtype=np.float32)
            if matrix.shape[1] != len(fields):
                raise ValueError(f"PCD ASCII column count mismatch: {path}")
        elif mode == "binary":
            dtype = self._structured_dtype(header, fields)
            with path.open("rb") as stream:
                stream.seek(data_offset)
                records = np.fromfile(stream, dtype=dtype, count=points)
            matrix = np.column_stack(
                [records[field].astype(np.float32, copy=False) for field in fields]
            )
        elif mode == "binary_compressed":
            raise ValueError("binary_compressed PCD is not supported; use binary or ASCII")
        else:
            raise ValueError(f"unsupported PCD DATA mode {mode!r}: {path}")
        if points and len(matrix) != points:
            raise ValueError(
                f"PCD point count mismatch: header={points}, loaded={len(matrix)}"
            )
        indices = {name: index for index, name in enumerate(fields)}
        xyz = matrix[:, [indices["x"], indices["y"], indices["z"]]]
        valid = np.isfinite(xyz).all(axis=1)
        invalid_count = int((~valid).sum())
        xyz = np.ascontiguousarray(xyz[valid], dtype=np.float32)
        attributes = {
            name: np.ascontiguousarray(matrix[:, index][valid], dtype=np.float32)
            for name, index in indices.items()
            if name not in {"x", "y", "z"}
        }
        return PointCloudData(
            xyz=xyz,
            attributes=attributes,
            sensor_id=sensor_id,
            return_id=return_id,
            source_frame=spec.source_frame,
            source_path=path,
            invalid_point_count=invalid_count,
            metadata={"raw_point_count": len(matrix), "columns": fields, "format": "pcd"},
        )

    @staticmethod
    def _read_header(path: Path) -> tuple[dict[str, list[str]], int]:
        header: dict[str, list[str]] = {}
        with path.open("rb") as stream:
            while True:
                line = stream.readline()
                if not line:
                    raise ValueError(f"PCD header is missing DATA: {path}")
                try:
                    text = line.decode("ascii").strip()
                except UnicodeDecodeError as exc:
                    raise ValueError(f"invalid PCD header: {path}") from exc
                if not text or text.startswith("#"):
                    continue
                parts = text.split()
                key = parts[0].upper()
                header[key] = parts[1:]
                if key == "DATA":
                    return header, stream.tell()

    @staticmethod
    def _structured_dtype(
        header: dict[str, list[str]], fields: tuple[str, ...]
    ) -> np.dtype:
        sizes = [int(value) for value in header.get("SIZE", [])]
        types = [value.upper() for value in header.get("TYPE", [])]
        if len(sizes) != len(fields) or len(types) != len(fields):
            raise ValueError("PCD binary header requires SIZE and TYPE per field")
        formats = []
        for size, value_type in zip(sizes, types):
            code = {"F": "f", "I": "i", "U": "u"}.get(value_type)
            if code is None or size not in {1, 2, 4, 8}:
                raise ValueError(f"unsupported PCD field type: TYPE={value_type} SIZE={size}")
            formats.append(np.dtype(f"<{code}{size}"))
        return np.dtype({"names": fields, "formats": formats})

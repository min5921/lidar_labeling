from __future__ import annotations

import numpy as np
from numpy.typing import ArrayLike, NDArray


def validate_rigid_transform(matrix: ArrayLike, atol: float = 1e-5) -> NDArray[np.float64]:
    transform = np.asarray(matrix, dtype=np.float64)
    if transform.shape != (4, 4):
        raise ValueError("transform must have shape [4, 4]")
    if not np.isfinite(transform).all():
        raise ValueError("transform values must be finite")
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=atol):
        raise ValueError("transform last row must be [0, 0, 0, 1]")
    rotation = transform[:3, :3]
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=atol):
        raise ValueError("rotation must be orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=atol):
        raise ValueError("rotation determinant must be +1")
    return transform


def transform_xyz(xyz: ArrayLike, matrix: ArrayLike) -> NDArray[np.float32]:
    points = np.asarray(xyz, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("xyz must have shape [N, 3]")
    transform = validate_rigid_transform(matrix)
    rotated = points.astype(np.float64) @ transform[:3, :3].T
    translated = rotated + transform[:3, 3]
    return translated.astype(np.float32, copy=False)


def invert_transform(matrix: ArrayLike) -> NDArray[np.float64]:
    transform = validate_rigid_transform(matrix)
    rotation = transform[:3, :3]
    translation = transform[:3, 3]
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation.T
    result[:3, 3] = -(rotation.T @ translation)
    return result


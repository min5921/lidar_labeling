from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def corners(box: dict[str, float]) -> np.ndarray:
    length = box["length"] / 2.0
    width = box["width"] / 2.0
    height = box["height"] / 2.0
    local = np.array(
        [
            [sx * length, sy * width, sz * height]
            for sz in (-1, 1)
            for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1))
        ]
    )
    yaw = box["heading"]
    rotation = np.array(
        [[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]]
    )
    return local @ rotation.T + np.array([box["center_x"], box["center_y"], box["center_z"]])


def project(points_vehicle: np.ndarray, calibration: dict[str, object]) -> np.ndarray:
    transform = np.asarray(calibration["extrinsic"]["transform"], dtype=float).reshape(4, 4)
    points_h = np.column_stack((points_vehicle, np.ones(len(points_vehicle))))
    camera = points_h @ np.linalg.inv(transform).T
    depth = camera[:, 0]
    normalized_x = -camera[:, 1] / depth
    normalized_y = -camera[:, 2] / depth
    fu, fv, cu, cv, k1, k2, p1, p2, k3 = calibration["intrinsic"]
    radius2 = normalized_x**2 + normalized_y**2
    radial = 1 + k1 * radius2 + k2 * radius2**2 + k3 * radius2**3
    distorted_x = normalized_x * radial + 2 * p1 * normalized_x * normalized_y + p2 * (
        radius2 + 2 * normalized_x**2
    )
    distorted_y = normalized_y * radial + p1 * (radius2 + 2 * normalized_y**2) + 2 * p2 * normalized_x * normalized_y
    return np.column_stack((fu * distorted_x + cu, fv * distorted_y + cv, depth))


def rectangle(projected: np.ndarray, width: int, height: int) -> tuple[float, float, float, float] | None:
    visible = projected[:, 2] > 0.1
    if not visible.any():
        return None
    uv = projected[visible, :2]
    min_uv = np.maximum(uv.min(axis=0), [0, 0])
    max_uv = np.minimum(uv.max(axis=0), [width - 1, height - 1])
    if np.any(max_uv <= min_uv):
        return None
    return (float(min_uv[0]), float(min_uv[1]), float(max_uv[0]), float(max_uv[1]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--frame", default="frame_000")
    parser.add_argument("--camera", default="FRONT")
    args = parser.parse_args()
    segment = json.loads((args.dataset / "segment.json").read_text())
    laser = json.loads((args.dataset / args.frame / "labels" / "laser_labels.json").read_text())
    groups = json.loads(
        (args.dataset / args.frame / "labels" / "projected_lidar_labels.json").read_text()
    )
    calibration = next(item for item in segment["camera_calibrations"] if item["name"] == args.camera)
    source = {
        item["id"].removesuffix(f"_{args.camera}"): item["box"]
        for group in groups
        if group["name"] == args.camera
        for item in group.get("labels", [])
    }
    differences: list[float] = []
    for item in laser:
        expected = source.get(item["id"])
        if expected is None:
            continue
        box = item.get("camera_synced_box") or item["box"]
        actual = rectangle(project(corners(box), calibration), calibration["width"], calibration["height"])
        if actual is None:
            continue
        expected_rect = np.array(
            [
                expected["center_x"] - expected["width"] / 2,
                expected["center_y"] - expected["length"] / 2,
                expected["center_x"] + expected["width"] / 2,
                expected["center_y"] + expected["length"] / 2,
            ]
        )
        error = float(np.abs(np.asarray(actual) - expected_rect).mean())
        differences.append(error)
    print(f"matches={len(differences)}")
    if differences:
        print(f"mean_abs_edge_error_px={np.mean(differences):.3f}")
        print(f"median_abs_edge_error_px={np.median(differences):.3f}")
        print(f"max_abs_edge_error_px={np.max(differences):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

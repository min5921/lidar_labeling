from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import (
    FrameSessionService,
    compare_calibration_context,
    compare_label_context,
)
from tests.fixture_builders import create_v2_dataset


def _calibrated_dataset(root: Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    manifest = create_v2_dataset(root, with_camera=True)
    identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    calibration = {
        "schema_version": "1.0",
        "reference_frame": "lidar:AEVA",
        "lidars": {"aeva": {"T_reference_sensor": identity}},
        "cameras": {
            "head_camera": {
                "intrinsic": [[100, 0, 16], [0, 100, 12], [0, 0, 1]],
                "T_camera_reference": identity,
                "image_size": [32, 24],
                "distortion_model": "none",
            }
        },
    }
    path = root / "generations" / "generation-000001" / "calibration.json"
    path.write_text(json.dumps(calibration), encoding="utf-8")
    manifest["profiles"][0]["camera"] = {
        "camera_id": "head_camera",
        "mode": "calibrated",
        "calibration_path": path.relative_to(root).as_posix(),
        "calibration_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    (root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest, calibration


@pytest.mark.parametrize("save_first", [False, True])
@pytest.mark.parametrize("remove_file", [False, True])
def test_live_calibration_change_warns_and_preserves_lidar_editing(
    tmp_path: Path, save_first: bool, remove_file: bool,
) -> None:
    path, _, calibration = _calibrated_dataset(tmp_path)
    adapter = DeviceCentricV2Adapter(tmp_path)
    repository = V2LabelRepository.for_sidecar(adapter)
    service = FrameSessionService(adapter, WaymoLabelImporter({}), repository)
    opened = service.open_frame("000000")
    label = repository.save(opened.label) if save_first else opened.label
    assert compare_calibration_context(label, opened.source) == ()

    if remove_file:
        path.unlink()
    else:
        calibration["cameras"]["head_camera"]["T_camera_reference"][0][3] = 9
        path.write_text(json.dumps(calibration), encoding="utf-8")

    assert {issue.code for issue in compare_label_context(label, opened.source)} == {
        "calibration_runtime_changed",
    }
    next_frame = service.open_frame("000001")
    assert {issue.code for issue in next_frame.context_issues} == {
        "calibration_runtime_changed",
    }
    assert adapter.load_cloud_from_source(opened.source, "aeva").point_count == 1
    saved = repository.save(label)
    assert saved.calibration_state["effective_mode"] == "display_only"
    assert saved.calibration_state["status"] == ("missing" if remove_file else "invalid")


def test_reopened_valid_calibration_only_warns_about_saved_context(tmp_path: Path) -> None:
    path, manifest, calibration = _calibrated_dataset(tmp_path)
    adapter = DeviceCentricV2Adapter(tmp_path)
    repository = V2LabelRepository.for_sidecar(adapter)
    label = WaymoLabelImporter({}).import_laser_labels(adapter.load_source_frame("000000"))
    repository.save(label)
    calibration["cameras"]["head_camera"]["T_camera_reference"][0][3] = 9
    path.write_text(json.dumps(calibration), encoding="utf-8")
    manifest["profiles"][0]["camera"]["calibration_sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (tmp_path / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")

    reopened_adapter = DeviceCentricV2Adapter(tmp_path)
    reopened_repository = V2LabelRepository.for_sidecar(reopened_adapter)
    opened = FrameSessionService(
        reopened_adapter, WaymoLabelImporter({}), reopened_repository,
    ).open_frame("000000")
    codes = {issue.code for issue in opened.context_issues}
    assert "calibration_changed" in codes
    assert "calibration_runtime_changed" not in codes
    assert reopened_adapter.camera_calibration_count == 1
    assert reopened_repository.save(opened.label).calibration_state["status"] == "valid"


@pytest.mark.parametrize("defect", ["schema", "reference", "transform", "fisheye", "disabled"])
def test_matching_hash_does_not_make_invalid_calibration_valid(
    tmp_path: Path, defect: str,
) -> None:
    path, manifest, calibration = _calibrated_dataset(tmp_path)
    if defect == "schema":
        calibration = {}
    elif defect == "reference":
        calibration["reference_frame"] = "other_lidar"
    elif defect == "transform":
        calibration["cameras"]["head_camera"]["T_camera_reference"][0][0] = 2
    elif defect == "fisheye":
        calibration["cameras"]["head_camera"]["distortion_model"] = "fisheye"
    else:
        calibration["cameras"]["head_camera"]["enabled"] = False
    path.write_text(json.dumps(calibration), encoding="utf-8")
    manifest["profiles"][0]["camera"]["calibration_sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    (tmp_path / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")

    adapter = DeviceCentricV2Adapter(tmp_path)
    repository = V2LabelRepository.for_sidecar(adapter)
    source = adapter.load_source_frame("000000")
    label = WaymoLabelImporter({}).import_laser_labels(source)
    assert adapter.camera_calibration_count == 0
    assert adapter.load_cloud_from_source(source, "aeva").point_count == 1
    saved = repository.save(label)
    assert saved.calibration_state["status"] == ("disabled" if defect == "disabled" else "invalid")
    assert saved.calibration_state["effective_mode"] == "display_only"

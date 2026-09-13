from __future__ import annotations

from dataclasses import replace
import json
from unittest.mock import patch

import numpy as np
import pytest

from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.services.background_task import TaskCancelled, TaskControl
from lidar_label_tool.services.object_tracking import TrackingResult, track_object
from lidar_label_tool.services.tracking_qa import TrackingQaOptions, validate_tracking_sample
from scripts.validate_tracking_sample import main
from tests.fixture_builders import CLASS_MAPPING, create_device_dataset, source_object, write_source_labels


@pytest.fixture
def dataset(tmp_path):
    root = tmp_path / "한글 추적 참고 QA"
    root.mkdir()
    create_device_dataset(root, frame_count=3)
    rng = np.random.default_rng(8)
    shapes = (rng.uniform(-.45, .45, (500, 3)), rng.uniform(-.45, .45, (500, 3)))
    for frame in range(3):
        objects = []
        points = []
        for index, source_type in enumerate(("TYPE_VEHICLE", "TYPE_SIGN")):
            obj = source_object(f"object_{index}", source_type)
            box = obj["box"]
            box.update({
                "center_x": 10 + index * 12 + frame * .8, "center_y": 2 + frame * .2,
                "center_z": (3.5 if index else .8) + frame * .1,
                "length": 2 if index else 4, "width": .25 if index else 2,
                "height": 1 if index else 1.6, "heading": 0,
            })
            cloud = shapes[index] * [box["length"], box["width"], box["height"]]
            cloud += [box["center_x"], box["center_y"], box["center_z"]]
            points.append(cloud)
            objects.append(obj)
        xyz = np.concatenate(points)
        np.column_stack((xyz, np.ones(len(xyz)))).astype("<f4").tofile(
            root / "sensors" / "lidar" / "MERGED" / f"{frame:06d}.bin",
        )
        write_source_labels(root, f"{frame:06d}", objects)
    return root


def _snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_reference_qa_uses_one_sensor_hides_future_labels_keeps_floating_sign_and_never_writes(dataset):
    working = dataset / "annotations" / "lidar_label_tool" / "000000.json"
    working.parent.mkdir(parents=True)
    working.write_text("working label intentionally not readable", encoding="utf-8")
    original = _snapshot(dataset)
    observed = []

    def inspected_tracking(request, target, clouds):
        assert request.lidar_ids == ("MERGED",)
        assert target.objects == ()
        assert request.options.ground_contact is False
        original_xyz = request.clouds[0].xyz.copy()
        result = track_object(request, target, clouds)
        np.testing.assert_array_equal(request.clouds[0].xyz, original_xyz)
        if request.obj.class_name == "Sign":
            assert result.box.z - result.box.height / 2 > 2.5
        observed.append(result)
        return result

    with patch("lidar_label_tool.services.tracking_qa.track_object", side_effect=inspected_tracking):
        report = validate_tracking_sample(
            open_dataset_adapter(dataset), CLASS_MAPPING, lidar_id="MERGED",
            options=TrackingQaOptions(max_frames=3, max_objects_per_pair=2),
        )
    assert len(observed) == 4
    assert report["summary"]["accepted_count"] == 4
    assert report["summary"]["accepted_center_error_m"]["max"] < .15
    assert report["by_class"]["Sign"]["accepted_count"] == 2
    assert report["source_integrity"] == "unchanged"
    assert report["verified_input_file_count"] == 6
    assert report["size_yaw_invariant"] == "passed"
    assert "인증이 아닙니다" in report["warning"]
    assert _snapshot(dataset) == original


def test_reference_qa_frame_object_budget_and_cli_json(dataset, capsys):
    original = _snapshot(dataset)
    assert main([
        str(dataset), "--lidar-id", "MERGED", "--max-frames", "2",
        "--max-objects-per-pair", "1", "--start-index", "1",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["frame_ids"] == ["000001", "000002"]
    assert report["summary"]["sample_count"] == 1
    assert _snapshot(dataset) == original
    assert main([str(dataset), "--lidar-id", "WRONG"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unknown LiDAR" in json.loads(captured.err)["error"]


@pytest.mark.parametrize("changes", [
    {"max_frames": 1}, {"max_objects_per_pair": 0}, {"start_index": -1}, {"max_distance_m": float("inf")},
])
def test_invalid_qa_limits_are_rejected(changes):
    with pytest.raises(ValueError):
        TrackingQaOptions(**changes)


def test_reference_qa_cancellation_and_missing_source_never_create_working_labels(dataset):
    original = _snapshot(dataset)
    control = TaskControl(lambda _: control.cancel())
    with pytest.raises(TaskCancelled):
        validate_tracking_sample(
            open_dataset_adapter(dataset), CLASS_MAPPING, lidar_id="MERGED",
            options=TrackingQaOptions(max_frames=3, max_objects_per_pair=1), control=control,
        )
    assert _snapshot(dataset) == original
    with patch("lidar_label_tool.io.labels.waymo_importer.WaymoLabelImporter.import_laser_labels", side_effect=ValueError("damaged label")):
        with pytest.raises(ValueError, match="damaged label"):
            validate_tracking_sample(open_dataset_adapter(dataset), CLASS_MAPPING, lidar_id="MERGED")
    assert _snapshot(dataset) == original


@pytest.mark.parametrize("violation", ["dimensions", "fallback", "ground"])
def test_qa_invariants_fail_loudly_if_tracker_breaks_contract(dataset, violation):
    original = _snapshot(dataset)
    def broken(request, target, clouds):
        box = request.obj.box3d
        if violation == "dimensions":
            box = replace(box, height=box.height + 1)
        if violation == "fallback":
            box = replace(box, x=box.x + 1)
        return TrackingResult(
            request.obj.id, request.source_frame_id, target.frame_id, box,
            "no_match", "fallback", ground_contact=violation == "ground",
        )
    with patch("lidar_label_tool.services.tracking_qa.track_object", side_effect=broken):
        with pytest.raises(AssertionError):
            validate_tracking_sample(open_dataset_adapter(dataset), CLASS_MAPPING, lidar_id="MERGED")
    assert _snapshot(dataset) == original


def test_reference_qa_detects_external_input_change_during_comparison(dataset):
    point_path = dataset / "sensors" / "lidar" / "MERGED" / "000000.bin"
    original = point_path.read_bytes()
    def changed(request, target, clouds):
        result = track_object(request, target, clouds)
        point_path.write_bytes(original + b"changed externally")
        return result
    with patch("lidar_label_tool.services.tracking_qa.track_object", side_effect=changed):
        with pytest.raises(ValueError, match="input changed during QA"):
            validate_tracking_sample(
                open_dataset_adapter(dataset), CLASS_MAPPING, lidar_id="MERGED",
                options=TrackingQaOptions(max_frames=2, max_objects_per_pair=1),
            )

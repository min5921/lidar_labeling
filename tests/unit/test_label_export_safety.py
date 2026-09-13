from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import struct

import pytest

from lidar_label_tool.app.config import load_config
from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.repository_factory import open_label_repository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.dataset_profiles import list_dataset_profiles
from lidar_label_tool.services.frame_session import FrameSessionService
from lidar_label_tool.services.label_export import export_dataset_labels
from tests.fixture_builders import create_device_dataset, create_v2_dataset


def _config() -> dict:
    return load_config(Path(__file__).resolve().parents[2] / "configs" / "default.json")


@pytest.mark.parametrize(
    "destination", ["working", "other_profile", "external", "external_other_profile", "manifest"]
)
def test_export_cannot_replace_or_create_working_labels(tmp_path: Path, destination: str) -> None:
    root = tmp_path / "dataset"
    create_v2_dataset(root, frame_count=1)
    adapter = DeviceCentricV2Adapter(root)
    adapter.scan()
    workspace = tmp_path / "workspace" if destination.startswith("external") else None
    repository = open_label_repository(adapter, workspace_root=workspace)
    session = FrameSessionService(adapter, WaymoLabelImporter({}, "device_centric_v2"), repository)
    label = repository.save(session.open_frame("000000").label)
    saved_path = repository.path_for(label.frame_id)
    original = saved_path.read_bytes()
    manifest = (root / "dataset.json").read_bytes()
    target = repository.annotation_dir
    if destination == "other_profile":
        target = root / "annotations" / "lidar_label_tool" / "other" / "aeva"
    elif destination == "external_other_profile":
        assert workspace is not None
        target = workspace / adapter.manifest.dataset_id / "annotations/lidar_label_tool/other/aeva"
    elif destination == "manifest":
        target = root / "dataset.json"
    with pytest.raises((ValueError, FileExistsError)):
        export_dataset_labels(
            root, config=_config(), export_format="centerpoint_intermediate_json",
            output=target, workspace_root=workspace,
        )
    assert saved_path.read_bytes() == original
    assert (root / "dataset.json").read_bytes() == manifest
    if destination in {"other_profile", "external_other_profile"}:
        assert not target.exists()


@pytest.mark.parametrize("destination", ["labels/laser_labels.json", "metadata.json", "lidar", "camera"])
def test_export_never_injects_new_files_into_waymo_frames(
    tmp_path: Path, destination: str
) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    (root / "schema.json").write_text(json.dumps({
        "lidar_bin": {"columns": ["x", "y", "z", "intensity"]},
        "coordinates": "vehicle frame",
    }), encoding="utf-8")
    (root / "segment.json").write_text(json.dumps({
        "scene_name": "waymo_fixture", "laser_calibrations": [{"name": "TOP"}],
    }), encoding="utf-8")
    frame = root / "frame_000"
    (frame / "lidar").mkdir(parents=True)
    (frame / "camera").mkdir()
    point = frame / "lidar/TOP_return1.bin"
    point.write_bytes(struct.pack("<4f", 1, 2, 3, 0.5))
    original = point.read_bytes()
    with pytest.raises(ValueError, match="raw input"):
        export_dataset_labels(
            root, config=_config(), export_format="lidar_label_json", output=frame / destination,
        )
    assert point.read_bytes() == original
    assert not (frame / "labels").exists()
    assert not (frame / "metadata.json").exists()


@pytest.mark.parametrize("destination", ["lidar", "camera", "timestamp", "inactive_lidar"])
def test_v2_export_protects_all_declared_sensor_inputs(tmp_path: Path, destination: str) -> None:
    root = tmp_path / "dataset"
    create_v2_dataset(root, frame_count=1, with_camera=True)
    manifest_path = root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    inactive = dict(manifest["lidars"][0])
    inactive["id"] = "inactive"
    inactive["data_pattern"] = "separate_sensor/frames/{sample_id}.bin"
    manifest["lidars"].append(inactive)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target = root / {
        "lidar": "sensors/lidar/AEVA/frames",
        "camera": "sensors/camera/HEAD_CAMERA/images",
        "timestamp": "timestamps",
        "inactive_lidar": "separate_sensor/frames",
    }[destination]
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="raw input"):
        export_dataset_labels(
            root, config=_config(), export_format="lidar_label_json", output=target,
        )
    after = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_external_data_root_is_protected_but_configuration_exports_remain_usable(
    tmp_path: Path,
) -> None:
    source = tmp_path / "raw_data"
    create_v2_dataset(source, frame_count=1)
    config_root = tmp_path / "configuration"
    config_root.mkdir()
    shutil.copytree(source / "generations", config_root / "generations")
    manifest = json.loads((source / "dataset.json").read_text(encoding="utf-8"))
    manifest["data_root"] = {"kind": "absolute_local", "path": str(source)}
    (config_root / "dataset.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="raw input"):
        export_dataset_labels(
            config_root, config=_config(), export_format="lidar_label_json",
            output=source / "sensors/lidar/AEVA/frames",
        )
    result = export_dataset_labels(
        config_root, config=_config(), export_format="lidar_label_json",
        output=config_root / "exports",
    )
    assert result.exported_paths == (config_root / "exports/000000.json",)


@pytest.mark.parametrize("pattern", ["lidar/{sample_id}.bin", "{sample_id}/lidar/points.bin"])
@pytest.mark.parametrize("missing", [False, True])
def test_v1_export_protects_declared_input_patterns(
    tmp_path: Path, pattern: str, missing: bool
) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    create_device_dataset(root)
    manifest_path = root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sensors"][0]["data_patterns"]["return1"] = pattern
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    point = root / pattern.format(sample_id="000000")
    point.parent.mkdir(parents=True)
    if not missing:
        point.write_bytes(struct.pack("<4f", 1, 2, 3, 0.5))
    with pytest.raises(ValueError, match="raw input"):
        export_dataset_labels(
            root, config=_config(), export_format="lidar_label_json", output=point.parent,
        )
    assert not (point.parent / "000000.json").exists()


def test_flat_input_pattern_does_not_block_normal_exports(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    create_device_dataset(root)
    manifest_path = root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sensors"][0]["data_patterns"]["return1"] = "{sample_id}.bin"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / "000000.bin").write_bytes(struct.pack("<4f", 1, 2, 3, 0.5))
    with pytest.raises(ValueError, match="raw input"):
        export_dataset_labels(
            root, config=_config(), export_format="lidar_label_json", output=root / "missing.bin",
        )
    result = export_dataset_labels(
        root, config=_config(), export_format="lidar_label_json", output=root / "exports",
    )
    assert result.exported_paths == (root / "exports/000000.json",)


@pytest.mark.parametrize("filename", ["points.bin", "000000.json"])
def test_dynamic_sample_directory_checks_batch_filenames_without_rejecting_exports(
    tmp_path: Path, filename: str
) -> None:
    root = tmp_path / "dataset"
    root.mkdir()
    create_device_dataset(root)
    manifest_path = root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pattern = "{sample_id}/" + filename
    manifest["sensors"][0]["data_patterns"]["return1"] = pattern
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    point = root / pattern.format(sample_id="000000")
    point.parent.mkdir()
    point.write_bytes(struct.pack("<4f", 1, 2, 3, 0.5))
    output = root / "exports"
    if filename.endswith(".json"):
        with pytest.raises(ValueError, match="raw input"):
            export_dataset_labels(
                root, config=_config(), export_format="lidar_label_json", output=output,
            )
        assert not output.exists()
    else:
        result = export_dataset_labels(
            root, config=_config(), export_format="lidar_label_json", output=output,
        )
        assert result.exported_paths == (output / "000000.json",)


@pytest.mark.parametrize("dangling", [False, True])
def test_export_symlinks_cannot_bypass_input_protection(tmp_path: Path, dangling: bool) -> None:
    root = tmp_path / "dataset"
    create_v2_dataset(root, frame_count=1)
    link = tmp_path / "linked-output"
    raw_directory = root / "sensors/lidar/AEVA/frames"
    destination = raw_directory / "missing.json" if dangling else raw_directory
    try:
        link.symlink_to(destination, target_is_directory=not dangling)
    except OSError:
        pytest.skip("symlink creation requires filesystem/Windows privileges")
    with pytest.raises((ValueError, FileExistsError)):
        export_dataset_labels(
            root, config=_config(), export_format="lidar_label_json", output=link,
        )
    assert not (raw_directory / "000000.json").exists()
    assert not (raw_directory / "missing.json").exists()


def test_existing_dotted_directory_is_not_treated_as_single_file(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    create_v2_dataset(root, frame_count=1)
    output = tmp_path / "export.v2"
    output.mkdir()
    result = export_dataset_labels(
        root, config=_config(), export_format="lidar_label_json", output=output,
    )
    assert result.exported_paths == (output / "000000.json",)


def test_nondefault_profile_exports_its_own_saved_objects(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    create_v2_dataset(root, frame_count=1)
    manifest_path = root / "dataset.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    alternate = json.loads(json.dumps(manifest["profiles"][0]))
    alternate["id"] = "alternate_profile"
    alternate["display_name"] = "다른 작업 profile"
    original_index = root / alternate["frame_index"]["path"]
    record = json.loads(original_index.read_text(encoding="utf-8"))
    record["profile_id"] = alternate["id"]
    index_bytes = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
    index_path = original_index.with_name("alternate_profile.frames.jsonl")
    index_path.write_bytes(index_bytes)
    alternate["frame_index"]["path"] = index_path.relative_to(root).as_posix()
    alternate["frame_index"]["sha256"] = hashlib.sha256(index_bytes).hexdigest()
    manifest["profiles"].append(alternate)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    profiles = list_dataset_profiles(root)
    assert [item.id for item in profiles] == ["aeva_profile", "alternate_profile"]

    adapter = DeviceCentricV2Adapter(root, "alternate_profile")
    adapter.scan()
    repository = open_label_repository(adapter)
    label = FrameSessionService(
        adapter, WaymoLabelImporter({}, "device_centric_v2"), repository
    ).open_frame("000000").label
    obj = LabeledObject("alternate-only", "car", Box3D(1, 2, 3, 4, 2, 1, 0))
    repository.save(replace(label, objects=(obj,)))
    result = export_dataset_labels(
        root, config=_config(), export_format="lidar_label_json",
        output=tmp_path / "exports", profile_id="alternate_profile",
    )
    payload = json.loads(result.exported_paths[0].read_text(encoding="utf-8"))
    assert [item["id"] for item in payload["objects"]] == ["alternate-only"]


def test_legacy_dataset_has_no_profile_choices(tmp_path: Path) -> None:
    create_device_dataset(tmp_path)
    assert list_dataset_profiles(tmp_path) == ()

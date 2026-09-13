from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from lidar_label_tool.app.config import load_config
from lidar_label_tool.domain.labels import Box3D, LabeledObject
from lidar_label_tool.io.adapters.factory import open_dataset_adapter
from lidar_label_tool.io.labels.repository_factory import open_label_repository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.exporters.batch import ExportBatchCancelled
from lidar_label_tool.services.background_task import TaskCancelled, TaskControl, TaskProgress
from lidar_label_tool.services.frame_session import FrameSessionService
from lidar_label_tool.services.label_export import export_dataset_labels, parse_export_class_mapping
from tests.fixture_builders import CLASS_MAPPING, create_device_dataset, create_v2_dataset


def _configuration() -> dict:
    return load_config(Path(__file__).resolve().parents[2] / "configs/default.json")


def _make_dataset(root: Path, version: int) -> None:
    root.mkdir()
    if version == 1:
        create_device_dataset(root, frame_count=2)
        class_name = "Car"
    else:
        create_v2_dataset(root, frame_count=2)
        class_name = "car"
    adapter = open_dataset_adapter(root)
    repository = open_label_repository(adapter)
    session = FrameSessionService(adapter, WaymoLabelImporter(CLASS_MAPPING), repository)
    for frame_id in ("000000", "000001"):
        label = session.open_frame(frame_id).label
        obj = LabeledObject(
            id="current-id", class_name=class_name, box3d=Box3D(1, 2, 0.8, 4, 2, 1.6, 0),
            attributes={"speed_x": 1.5}, extra_fields={"tracking_history": [{"value": 1}]},
            source={"format": "device_centric_json", "raw": {
                "id": "source-id", "type": "TYPE_VEHICLE", "vendor": "preserve",
                "box": {"center_x": 0, "center_y": 0, "center_z": 0,
                        "length": 4, "width": 2, "height": 1.6, "heading": 0},
                "metadata": {"speed_x": 1.5},
            }},
        )
        repository.save(replace(label, objects=(obj,)))


def _bytes(root: Path) -> dict:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("version", [1, 2])
def test_source_export_explicit_mapping_reports_loss_and_preserves_working_data(tmp_path: Path, version: int) -> None:
    root = tmp_path / "dataset"
    _make_dataset(root, version)
    before = _bytes(root)
    output = tmp_path / "exports"
    class_name = "Car" if version == 1 else "car"
    result = export_dataset_labels(
        root, config=_configuration(), export_format="source_laser_json", output=output,
        export_class_mapping={class_name: "TYPE_CUSTOM_VEHICLE"},
    )
    assert result.frame_count == 2 and len(result.reports) == 2
    for path in result.exported_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document[0]["type"] == "TYPE_CUSTOM_VEHICLE"
        assert document[0]["id"] == "current-id"
        assert document[0]["vendor"] == "preserve"
        assert document[0]["box"]["center_x"] == 1
    assert result.reports[0]["changed_id_object_ids"] == ("current-id",)
    assert result.reports[0]["changed_type_object_ids"] == ("current-id",)
    assert "current-id.tracking_history" in result.reports[0]["omitted_object_fields"]
    assert result.reports[0]["warnings"]
    assert _bytes(root) == before


def test_v2_source_export_without_explicit_or_taxonomy_mapping_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _make_dataset(root, 2)
    output = tmp_path / "exports"
    with pytest.raises(ValueError, match="mapping"):
        export_dataset_labels(root, config=_configuration(), export_format="source_laser_json", output=output)
    assert not output.exists()


@pytest.mark.parametrize("stage", ["before", "export_read", "export_validate"])
def test_export_cancel_before_writes_preserves_all_inputs(tmp_path: Path, stage: str) -> None:
    root = tmp_path / "dataset"
    _make_dataset(root, 2)
    before = _bytes(root)
    task = TaskControl(lambda update: task.cancel() if update.stage == stage else None)
    if stage == "before":
        task.cancel()
    output = tmp_path / "exports"
    with pytest.raises(TaskCancelled):
        export_dataset_labels(
            root, config=_configuration(), export_format="source_laser_json", output=output,
            export_class_mapping={"car": "TYPE_VEHICLE"}, task=task,
        )
    assert not output.exists()
    assert _bytes(root) == before


def test_export_batch_cancel_keeps_only_completed_outputs(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _make_dataset(root, 2)
    before = _bytes(root)
    output = tmp_path / "exports"
    def progress(update: TaskProgress) -> None:
        if update.stage == "export" and update.completed == 1:
            task.cancel()
    task = TaskControl(progress)
    with pytest.raises(ExportBatchCancelled) as caught:
        export_dataset_labels(
            root, config=_configuration(), export_format="source_laser_json", output=output,
            export_class_mapping={"car": "TYPE_VEHICLE"}, task=task,
        )
    assert caught.value.exported_paths == (output / "000000.json",)
    assert (output / "000000.json").is_file()
    assert not (output / "000001.json").exists()
    assert _bytes(root) == before


def test_source_export_existing_destination_is_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "dataset"
    _make_dataset(root, 1)
    output = tmp_path / "exports"
    output.mkdir()
    target = output / "000001.json"
    target.write_bytes(b"user export")
    with pytest.raises(FileExistsError):
        export_dataset_labels(root, config=_configuration(), export_format="source_laser_json", output=output)
    assert target.read_bytes() == b"user export"
    assert not (output / "000000.json").exists()


def test_export_mapping_parser_does_not_infer_or_silently_replace() -> None:
    assert parse_export_class_mapping("car = TYPE_VEHICLE") == {"car": "TYPE_VEHICLE"}
    for value in ("car", "car=", "=TYPE_VEHICLE", "car=A\ncar=B"):
        with pytest.raises(ValueError):
            parse_export_class_mapping(value)

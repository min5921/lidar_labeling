from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.domain.point_cloud import PointCloudSpec
from lidar_label_tool.io.dataset import SourceFrameData
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter
from lidar_label_tool.services.frame_session import (
    FrameSessionService,
    compare_label_context,
    refresh_label_context,
)


class _SourceOnlyAdapter:
    def __init__(self, source: SourceFrameData) -> None:
        self.source = source

    def load_source_frame(self, frame_id: str) -> SourceFrameData:
        if frame_id != self.source.frame_id:
            raise KeyError(frame_id)
        return self.source


def _source(root: Path) -> SourceFrameData:
    return SourceFrameData(
        dataset_root=root,
        dataset_id="dataset",
        frame_id="000000",
        point_cloud_paths={"MERGED": (root / "lidar" / "000000.bin",)},
        image_paths={},
        source_label_paths={"laser": root / "source_labels" / "000000.json"},
        point_spec=PointCloudSpec(
            columns=("x", "y", "z"), source_frame="robosense"
        ),
        metadata={
            "reference_frame": "robosense",
            "calibration_path": "calibration/calibration.json",
            "sensor_status": {"MERGED": "not_required"},
        },
    )


class FrameSessionContextTests(unittest.TestCase):
    def test_working_label_reports_changed_source_and_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _source(root)
            laser_path = source.source_label_paths["laser"]
            laser_path.parent.mkdir(parents=True)
            laser_path.write_text("[]", encoding="utf-8")
            calibration = root / "calibration" / "calibration.json"
            calibration.parent.mkdir()
            calibration.write_text('{"version":1}', encoding="utf-8")
            repository = LabelRepository.for_sidecar(root, "dataset")
            service = FrameSessionService(
                _SourceOnlyAdapter(source), WaymoLabelImporter({}), repository
            )
            imported = service.open_frame("000000")
            repository.save(imported.label)

            laser_path.write_text('[{"id":"new"}]', encoding="utf-8")
            calibration.write_text('{"version":2}', encoding="utf-8")

            reopened = service.open_frame("000000")

            self.assertEqual(reopened.label_origin, "working")
            self.assertEqual(
                {issue.code for issue in reopened.context_issues},
                {"source_changed", "calibration_changed"},
            )

    def test_refresh_label_context_acknowledges_current_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = _source(root)
            laser_path = source.source_label_paths["laser"]
            laser_path.parent.mkdir(parents=True)
            laser_path.write_text("[]", encoding="utf-8")
            calibration = root / "calibration" / "calibration.json"
            calibration.parent.mkdir()
            calibration.write_text('{"version":1}', encoding="utf-8")
            label = WaymoLabelImporter({}).import_laser_labels(source)
            laser_path.write_text("[ ]\n", encoding="utf-8")

            self.assertEqual(
                {issue.code for issue in compare_label_context(label, source)},
                {"source_changed"},
            )

            refreshed = refresh_label_context(label, source)

            self.assertEqual(compare_label_context(refreshed, source), ())

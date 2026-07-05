from pathlib import Path
import tempfile
import unittest

from lidar_label_tool.app.config import load_config
from lidar_label_tool.calibration.waymo_camera import (
    CameraCalibration,
    camera_synced_projection_box,
    project_box_wireframe,
)
from lidar_label_tool.io.adapters.frame_centric_waymo import WaymoFrameCentricAdapter
from lidar_label_tool.io.labels.json_repository import LabelRepository
from lidar_label_tool.io.labels.waymo_importer import WaymoLabelImporter, sha256_file
from lidar_label_tool.services.dataset_preflight import inspect_dataset


ROOT = Path(__file__).resolve().parents[2]
SAMPLE = (
    ROOT
    / "local_data"
    / "incoming"
    / "segment-175830748773502782_1580_000_1600_000_with_camera_labels"
)


@unittest.skipUnless(SAMPLE.is_dir(), "local Waymo sample is not available")
class WaymoSampleIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config(ROOT / "configs" / "default.json")
        cls.adapter = WaymoFrameCentricAdapter(SAMPLE)
        cls.index = cls.adapter.scan()
        cls.importer = WaymoLabelImporter(cls.config["source_class_mappings"])

    def test_scans_expected_sensors_and_frames(self) -> None:
        self.assertEqual(self.index.frame_count, 198)
        self.assertEqual(set(self.index.lidar_ids), {"TOP", "FRONT", "REAR", "SIDE_LEFT", "SIDE_RIGHT"})
        self.assertEqual(len(self.index.camera_ids), 5)
        self.assertEqual(len(self.index.point_spec.columns), 6)
        self.assertEqual(self.index.point_spec.source_frame, "vehicle")

    def test_loads_top_returns(self) -> None:
        return1 = self.adapter.load_point_cloud("frame_000", "TOP", "1")
        return2 = self.adapter.load_point_cloud("frame_000", "TOP", "2")
        self.assertEqual(return1.point_count, 152078)
        self.assertEqual(return2.point_count, 15874)
        self.assertEqual(return1.invalid_point_count, 0)
        self.assertIn("nlz_flag", return1.attributes)

    def test_imports_existing_labels_and_reference_layers(self) -> None:
        source = self.adapter.load_source_frame("frame_000")
        label = self.importer.import_laser_labels(source)
        counts = self.importer.class_counts(label)
        self.assertEqual(len(label.objects), 51)
        self.assertEqual(counts["Car"], 31)
        self.assertEqual(counts["Pedestrian"], 3)
        self.assertEqual(counts["Sign"], 17)
        self.assertTrue(all(isinstance(obj.id, str) and obj.id for obj in label.objects))
        layers = self.importer.load_reference_layers(source)
        self.assertEqual(len(layers["camera"]), 5)
        self.assertEqual(len(layers["projected_lidar"]), 5)

    def test_saving_working_label_does_not_modify_source(self) -> None:
        source = self.adapter.load_source_frame("frame_000")
        source_label_path = source.source_label_paths["laser"]
        before = sha256_file(source_label_path)
        imported = self.importer.import_laser_labels(source)
        with tempfile.TemporaryDirectory() as directory:
            repository = LabelRepository.for_workspace(Path(directory), imported.dataset_id)
            saved = repository.save(imported)
            self.assertEqual(saved.revision, 1)
            self.assertEqual(len(repository.load("frame_000").objects), 51)
        self.assertEqual(sha256_file(source_label_path), before)

    def test_preflight_summary_matches_sample_without_loading_points(self) -> None:
        preflight = inspect_dataset(SAMPLE, probe_write=False)
        self.assertEqual(preflight.frame_count, 198)
        self.assertEqual(len(preflight.lidar_ids), 5)
        self.assertEqual(len(preflight.camera_ids), 5)
        self.assertEqual(preflight.source_frame, "vehicle")
        self.assertEqual(preflight.camera_calibration_count, 5)
        self.assertIn("laser", preflight.source_label_layers)

    def test_live_camera_segments_are_clipped_to_image(self) -> None:
        source = self.adapter.load_source_frame("frame_080")
        label = self.importer.import_laser_labels(source)
        raw = next(
            item
            for item in self.adapter.segment["camera_calibrations"]
            if item["name"] == "FRONT"
        )
        calibration = CameraCalibration.from_waymo(raw)
        wireframes = {}
        for obj in label.objects:
            wireframe = project_box_wireframe(
                obj.id, camera_synced_projection_box(obj), calibration
            )
            wireframes[obj.id] = wireframe
            if not len(wireframe.segments):
                continue
            self.assertGreaterEqual(float(wireframe.segments.min()), 0.0)
            self.assertLessEqual(float(wireframe.segments[:, :, 0].max()), 1919.0)
            self.assertLessEqual(float(wireframe.segments[:, :, 1].max()), 1279.0)
        folded_outside = next(obj for obj in label.objects if obj.id.startswith("JY4OANJx"))
        front_left_raw = next(
            item
            for item in self.adapter.segment["camera_calibrations"]
            if item["name"] == "FRONT_LEFT"
        )
        front_left = CameraCalibration.from_waymo(front_left_raw)
        folded_wireframe = project_box_wireframe(
            folded_outside.id,
            camera_synced_projection_box(folded_outside),
            front_left,
        )
        self.assertEqual(len(folded_wireframe.segments), 0)

    def test_near_vehicle_edges_are_clipped_to_camera_frustum(self) -> None:
        source = self.adapter.load_source_frame("frame_006")
        label = self.importer.import_laser_labels(source)
        selected = next(
            obj for obj in label.objects if obj.id.startswith("zbLLemm8")
        )
        raw = next(
            item
            for item in self.adapter.segment["camera_calibrations"]
            if item["name"] == "FRONT"
        )
        calibration = CameraCalibration.from_waymo(raw)
        wireframe = project_box_wireframe(
            selected.id, camera_synced_projection_box(selected), calibration
        )
        self.assertGreater(len(wireframe.segments), 0)
        self.assertGreaterEqual(float(wireframe.segments[:, :, 0].min()), 1500.0)


if __name__ == "__main__":
    unittest.main()

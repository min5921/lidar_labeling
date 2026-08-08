from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication

from lidar_label_tool.app.config import default_config_path
from lidar_label_tool.domain.labels import Box3D, FrameLabel, LabeledObject
from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.ui.main_window import MainWindow
from tests.fixture_builders import create_v2_dataset


class V2MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_constructs_profile_scoped_editor_without_loading_inactive_lidar(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 GUI 데이터"
            root.mkdir()
            create_v2_dataset(root, with_camera=True)

            with patch.object(MainWindow, "_request_frame") as request_frame:
                window = MainWindow(
                    root,
                    default_config_path(),
                    profile_id="aeva_profile",
                )

            self.assertIsInstance(window.adapter, DeviceCentricV2Adapter)
            self.assertEqual(window.index.profile_id, "aeva_profile")
            self.assertEqual(window.index.lidar_ids, ("aeva",))
            self.assertEqual(tuple(window.sensor_checks), ("aeva",))
            self.assertEqual(
                [window.new_class_combo.itemText(index) for index in range(window.new_class_combo.count())],
                ["car"],
            )
            request_frame.assert_called_once_with("000000")
            window.close()

    def test_space_shortcut_moves_selected_box_up(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "Space shortcut dataset"
            root.mkdir()
            create_v2_dataset(root)

            with patch.object(MainWindow, "_request_frame"):
                window = MainWindow(
                    root,
                    default_config_path(),
                    profile_id="aeva_profile",
                )

            space_shortcut = next(
                shortcut
                for shortcut in window.shortcuts
                if shortcut.key() == QKeySequence(Qt.Key.Key_Space)
            )
            with patch.object(window, "_nudge_selected") as nudge_selected:
                space_shortcut.activated.emit()

            nudge_selected.assert_called_once_with("z", 1.0)
            window.close()

    def test_control_alone_moves_down_but_control_chord_does_not(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "Control shortcut dataset"
            root.mkdir()
            create_v2_dataset(root)

            with patch.object(MainWindow, "_request_frame"):
                window = MainWindow(
                    root,
                    default_config_path(),
                    profile_id="aeva_profile",
                )

            control_press = QKeyEvent(
                QEvent.Type.KeyPress,
                Qt.Key.Key_Control,
                Qt.KeyboardModifier.ControlModifier,
            )
            control_release = QKeyEvent(
                QEvent.Type.KeyRelease,
                Qt.Key.Key_Control,
                Qt.KeyboardModifier.NoModifier,
            )
            save_override = QKeyEvent(
                QEvent.Type.ShortcutOverride,
                Qt.Key.Key_S,
                Qt.KeyboardModifier.ControlModifier,
            )
            with patch.object(window, "_nudge_selected") as nudge_selected:
                QApplication.sendEvent(window, control_press)
                QApplication.sendEvent(window, control_release)
                nudge_selected.assert_called_once_with("z", -1.0)

                nudge_selected.reset_mock()
                QApplication.sendEvent(window, control_press)
                QApplication.sendEvent(window, save_override)
                QApplication.sendEvent(window, control_release)
                nudge_selected.assert_not_called()

            window.close()

    def test_z_nudge_uses_configured_move_step(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory) / "Z nudge dataset"
            root.mkdir()
            create_v2_dataset(root)

            with patch.object(MainWindow, "_request_frame"):
                window = MainWindow(
                    root,
                    default_config_path(),
                    profile_id="aeva_profile",
                )

            selected = LabeledObject(
                id="object-1",
                class_name="car",
                box3d=Box3D(
                    x=1.0,
                    y=2.0,
                    z=3.0,
                    length=4.0,
                    width=2.0,
                    height=1.5,
                    yaw=0.0,
                ),
            )
            label = FrameLabel(
                dataset_id="dataset-1",
                frame_id="000000",
                point_cloud_paths={"aeva": ("lidar/aeva/000000.bin",)},
                image_paths={},
                reference_frame="lidar:aeva",
                objects=(selected,),
            )
            window.move_step_spin.setValue(0.25)
            with (
                patch.object(window, "_shortcut_blocked", return_value=False),
                patch.object(window, "_selected_object", return_value=selected),
                patch.object(window, "_current_label", return_value=label),
                patch.object(window, "_apply_edited_label") as apply_edited_label,
            ):
                window._nudge_selected("z", -1.0)

            edited_label, selected_id = apply_edited_label.call_args.args
            self.assertEqual(selected_id, "object-1")
            self.assertAlmostEqual(edited_label.objects[0].box3d.z, 2.75)
            window.close()


if __name__ == "__main__":
    unittest.main()

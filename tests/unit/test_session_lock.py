from __future__ import annotations

import json
import ctypes
from ctypes import wintypes
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

from lidar_label_tool.services.session_lock import (
    SessionLock,
    SessionLockExistsError,
    SessionLockInfo,
    _pid_is_running,
)


def _info(pid: int = 1234, lock_id: str = "lock-a") -> SessionLockInfo:
    return SessionLockInfo(
        lock_id=lock_id,
        pid=pid,
        hostname=socket.gethostname(),
        username="tester",
        started_at_utc="2026-07-06T00:00:00Z",
        dataset_id="dataset-a",
        dataset_root="C:/dataset",
        workspace_root=None,
    )


class SessionLockTests(unittest.TestCase):
    def test_windows_process_handle_is_pointer_sized_and_closed(self) -> None:
        kernel = MagicMock()
        handle = 0x123456789ABC
        kernel.OpenProcess.return_value = handle
        def exit_code(actual: int, output: object) -> bool:
            self.assertEqual(actual, handle)
            ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = 259
            return True
        kernel.GetExitCodeProcess.side_effect = exit_code
        with patch("lidar_label_tool.services.session_lock.sys.platform", "win32"), \
             patch("ctypes.WinDLL", return_value=kernel, create=True), \
             patch("ctypes.set_last_error", create=True):
            self.assertTrue(_pid_is_running(123456))
        self.assertIs(kernel.OpenProcess.restype, wintypes.HANDLE)
        self.assertEqual(kernel.CloseHandle.argtypes, [wintypes.HANDLE])
        kernel.CloseHandle.assert_called_once_with(handle)

    def test_windows_denied_and_unknown_process_errors_are_conservatively_active(self) -> None:
        kernel = MagicMock()
        kernel.OpenProcess.return_value = None
        for error, expected in ((5, True), (8, True), (0, True), (87, False)):
            with self.subTest(error=error), \
                 patch("lidar_label_tool.services.session_lock.sys.platform", "win32"), \
                 patch("ctypes.WinDLL", return_value=kernel, create=True), \
                 patch("ctypes.set_last_error", create=True), \
                 patch("ctypes.get_last_error", return_value=error, create=True):
                self.assertEqual(_pid_is_running(123456), expected)
        kernel.CloseHandle.assert_not_called()

    def test_windows_exit_query_failure_preserves_lock_and_closes_handle(self) -> None:
        kernel = MagicMock()
        kernel.OpenProcess.return_value = 777
        kernel.GetExitCodeProcess.return_value = False
        with patch("lidar_label_tool.services.session_lock.sys.platform", "win32"), \
             patch("ctypes.WinDLL", return_value=kernel, create=True), \
             patch("ctypes.set_last_error", create=True):
            self.assertTrue(_pid_is_running(123456))
        kernel.CloseHandle.assert_called_once_with(777)

    def test_windows_exited_process_is_stale_even_while_a_handle_remains(self) -> None:
        kernel = MagicMock()
        kernel.OpenProcess.return_value = 777
        def exit_code(_handle: int, output: object) -> bool:
            ctypes.cast(output, ctypes.POINTER(wintypes.DWORD)).contents.value = 0
            return True
        kernel.GetExitCodeProcess.side_effect = exit_code
        with patch("lidar_label_tool.services.session_lock.sys.platform", "win32"), \
             patch("ctypes.WinDLL", return_value=kernel, create=True), \
             patch("ctypes.set_last_error", create=True):
            self.assertFalse(_pid_is_running(123456))
        kernel.CloseHandle.assert_called_once_with(777)

    def test_real_child_process_is_active_then_stale(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdin.read(1)"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            self.assertTrue(_pid_is_running(child.pid))
            child.communicate(input=b"x", timeout=5)
            self.assertFalse(_pid_is_running(child.pid))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_create_detect_and_release_lock(self) -> None:
        with TemporaryDirectory() as directory:
            lock = SessionLock(Path(directory), pid_checker=lambda pid: pid == 1234)
            lock.acquire(_info())

            self.assertEqual(lock.inspect().status, "active")
            self.assertTrue(lock.release())
            self.assertEqual(lock.inspect().status, "available")

    def test_existing_active_lock_requires_force(self) -> None:
        with TemporaryDirectory() as directory:
            first = SessionLock(Path(directory), pid_checker=lambda _pid: True)
            first.acquire(_info())
            second = SessionLock(Path(directory), pid_checker=lambda _pid: True)

            with self.assertRaises(SessionLockExistsError):
                second.acquire(_info(pid=5678, lock_id="lock-b"))

    def test_stale_lock_can_be_replaced_without_old_owner_deleting_new_lock(self) -> None:
        with TemporaryDirectory() as directory:
            first = SessionLock(Path(directory), pid_checker=lambda _pid: False)
            first.acquire(_info())
            self.assertEqual(first.inspect().status, "stale")

            second = SessionLock(Path(directory), pid_checker=lambda pid: pid == 5678)
            second.acquire(_info(pid=5678, lock_id="lock-b"), force=True)

            self.assertFalse(first.release())
            self.assertEqual(second.inspect().info.lock_id, "lock-b")  # type: ignore[union-attr]
            self.assertTrue(second.release())

    def test_malformed_lock_is_reported_and_replaceable(self) -> None:
        with TemporaryDirectory() as directory:
            lock = SessionLock(Path(directory), pid_checker=lambda _pid: False)
            lock.path.parent.mkdir(parents=True, exist_ok=True)
            lock.path.write_text("{bad-json", encoding="utf-8")

            inspection = lock.inspect()
            self.assertEqual(inspection.status, "malformed")
            self.assertIsNotNone(inspection.error)

            lock.acquire(_info(), force=True)
            self.assertEqual(json.loads(lock.path.read_text(encoding="utf-8"))["lock_id"], "lock-a")


if __name__ == "__main__":
    unittest.main()

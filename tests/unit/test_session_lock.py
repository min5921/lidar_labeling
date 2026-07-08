from __future__ import annotations

import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.services.session_lock import (
    SessionLock,
    SessionLockExistsError,
    SessionLockInfo,
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

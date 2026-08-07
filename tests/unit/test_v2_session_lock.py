from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidar_label_tool.io.adapters.device_centric_v2 import DeviceCentricV2Adapter
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.session_lock_v2 import (
    V2SessionLock,
    V2SessionLockInfo,
)
from tests.fixture_builders import create_v2_dataset


class V2SessionLockTests(unittest.TestCase):
    def test_lock_is_profile_scoped_and_schema_valid(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            repository = V2LabelRepository.for_sidecar(DeviceCentricV2Adapter(root))
            lock = V2SessionLock(repository, pid_checker=lambda _pid: True)
            info = V2SessionLockInfo.current(repository)

            lock.acquire(info)
            document = json.loads(lock.path.read_text(encoding="utf-8"))

            self.assertEqual(lock.inspect().status, "active")
            self.assertEqual(document["profile_id"], "aeva_profile")
            self.assertEqual(document["label_lidar_id"], "aeva")
            self.assertNotIn("frame_id", document)
            self.assertTrue(lock.release())
            self.assertFalse(lock.path.exists())

    def test_wrong_profile_identity_is_malformed_and_never_silently_reused(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            create_v2_dataset(root)
            repository = V2LabelRepository.for_sidecar(DeviceCentricV2Adapter(root))
            lock = V2SessionLock(repository, pid_checker=lambda _pid: True)
            document = V2SessionLockInfo.current(repository).to_dict()
            document["profile_id"] = "other_profile"
            lock.path.parent.mkdir(parents=True, exist_ok=True)
            lock.path.write_text(json.dumps(document), encoding="utf-8")

            inspection = lock.inspect()
            self.assertEqual(inspection.status, "malformed")
            self.assertIn("identity mismatch", inspection.error or "")


if __name__ == "__main__":
    unittest.main()

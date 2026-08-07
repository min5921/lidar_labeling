from __future__ import annotations

from lidar_label_tool.io.labels.repository_factory import WorkingLabelRepository
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.recovery import RecoveryStore
from lidar_label_tool.services.recovery_v2 import V2RecoveryStore


def open_recovery_store(
    repository: WorkingLabelRepository,
) -> RecoveryStore | V2RecoveryStore:
    if isinstance(repository, V2LabelRepository):
        return V2RecoveryStore(repository)
    return RecoveryStore(repository.annotation_dir)

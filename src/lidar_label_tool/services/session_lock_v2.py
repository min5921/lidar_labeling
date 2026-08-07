from __future__ import annotations

from dataclasses import dataclass
import getpass
import json
import os
from pathlib import Path
import socket
from typing import Any, Callable, Mapping
from uuid import uuid4

from lidar_label_tool import __version__
from lidar_label_tool.domain.labels import utc_now_iso
from lidar_label_tool.io.json_schema import validate_json_document
from lidar_label_tool.io.labels.v2_repository import V2LabelRepository
from lidar_label_tool.services.session_lock import LockStatus, _pid_is_running


@dataclass(frozen=True, slots=True)
class V2SessionLockInfo:
    dataset_id: str
    profile_id: str
    label_lidar_id: str
    reference_frame: str
    profile_sha256: str
    pid: int
    host: str
    owner: str
    started_at_utc: str
    heartbeat_at_utc: str
    tool_version: str
    nonce: str

    @property
    def hostname(self) -> str:
        return self.host

    @property
    def username(self) -> str:
        return self.owner

    @classmethod
    def current(cls, repository: V2LabelRepository) -> V2SessionLockInfo:
        try:
            owner = getpass.getuser()
        except (OSError, KeyError):
            owner = "unknown"
        now = utc_now_iso()
        return cls(
            dataset_id=repository.dataset_id,
            profile_id=repository.profile_id,
            label_lidar_id=repository.label_lidar_id,
            reference_frame=repository.reference_frame,
            profile_sha256=repository.adapter.profile_sha256,
            pid=os.getpid(),
            host=socket.gethostname(),
            owner=owner or "unknown",
            started_at_utc=now,
            heartbeat_at_utc=now,
            tool_version=__version__,
            nonce=uuid4().hex,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "kind": "profile_session_lock",
            "dataset_id": self.dataset_id,
            "profile_id": self.profile_id,
            "label_lidar_id": self.label_lidar_id,
            "reference_frame": self.reference_frame,
            "profile_sha256": self.profile_sha256,
            "pid": self.pid,
            "host": self.host,
            "owner": self.owner,
            "started_at_utc": self.started_at_utc,
            "heartbeat_at_utc": self.heartbeat_at_utc,
            "tool_version": self.tool_version,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> V2SessionLockInfo:
        validate_json_document(document, "session-lock-v2.schema.json")
        return cls(
            dataset_id=str(document["dataset_id"]),
            profile_id=str(document["profile_id"]),
            label_lidar_id=str(document["label_lidar_id"]),
            reference_frame=str(document["reference_frame"]),
            profile_sha256=str(document["profile_sha256"]),
            pid=int(document["pid"]),
            host=str(document["host"]),
            owner=str(document["owner"]),
            started_at_utc=str(document["started_at_utc"]),
            heartbeat_at_utc=str(document["heartbeat_at_utc"]),
            tool_version=str(document["tool_version"]),
            nonce=str(document["nonce"]),
        )


@dataclass(frozen=True, slots=True)
class V2SessionLockInspection:
    status: LockStatus
    info: V2SessionLockInfo | None = None
    error: str | None = None


class V2SessionLockExistsError(RuntimeError):
    def __init__(self, inspection: V2SessionLockInspection) -> None:
        self.inspection = inspection
        super().__init__(f"v2 session lock already exists: {inspection.status}")


class V2SessionLock:
    def __init__(
        self,
        repository: V2LabelRepository,
        *,
        pid_checker: Callable[[int], bool] = _pid_is_running,
    ) -> None:
        self.repository = repository
        self.path = repository.annotation_dir / ".session.lock"
        self._pid_checker = pid_checker
        self._owned: V2SessionLockInfo | None = None

    def inspect(self) -> V2SessionLockInspection:
        if not self.path.is_file():
            return V2SessionLockInspection("available")
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                document = json.load(stream)
            if not isinstance(document, Mapping):
                raise ValueError("v2 session lock root must be an object")
            info = V2SessionLockInfo.from_dict(document)
            expected = {
                "dataset_id": self.repository.dataset_id,
                "profile_id": self.repository.profile_id,
                "label_lidar_id": self.repository.label_lidar_id,
                "reference_frame": self.repository.reference_frame,
                "profile_sha256": self.repository.adapter.profile_sha256,
            }
            for key, value in expected.items():
                if getattr(info, key) != value:
                    raise ValueError(f"v2 session lock identity mismatch: {key}")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            return V2SessionLockInspection("malformed", error=str(exc))
        if info.host != socket.gethostname():
            return V2SessionLockInspection("active", info=info)
        status: LockStatus = "active" if self._pid_checker(info.pid) else "stale"
        return V2SessionLockInspection(status, info=info)

    def acquire(self, info: V2SessionLockInfo, *, force: bool = False) -> None:
        self._require_info_identity(info)
        inspection = self.inspect()
        if inspection.status != "available" and not force:
            raise V2SessionLockExistsError(inspection)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if force:
            temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
            try:
                self._write(temporary, info, exclusive=True)
                os.replace(temporary, self.path)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        else:
            try:
                self._write(self.path, info, exclusive=True)
            except FileExistsError as exc:
                raise V2SessionLockExistsError(self.inspect()) from exc
        self._owned = info

    def release(self) -> bool:
        if self._owned is None:
            return False
        inspection = self.inspect()
        if inspection.info is None or inspection.info.nonce != self._owned.nonce:
            self._owned = None
            return False
        self.path.unlink()
        self._owned = None
        return True

    @staticmethod
    def _write(path: Path, info: V2SessionLockInfo, *, exclusive: bool) -> None:
        document = info.to_dict()
        validate_json_document(document, "session-lock-v2.schema.json")
        with path.open("x" if exclusive else "w", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _require_info_identity(self, info: V2SessionLockInfo) -> None:
        expected = (
            self.repository.dataset_id,
            self.repository.profile_id,
            self.repository.label_lidar_id,
            self.repository.reference_frame,
            self.repository.adapter.profile_sha256,
        )
        actual = (
            info.dataset_id,
            info.profile_id,
            info.label_lidar_id,
            info.reference_frame,
            info.profile_sha256,
        )
        if actual != expected:
            raise ValueError("v2 session lock info identity does not match repository")

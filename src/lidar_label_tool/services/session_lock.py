from __future__ import annotations

from dataclasses import dataclass
import getpass
import json
import os
from pathlib import Path
import socket
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from lidar_label_tool.domain.labels import utc_now_iso


LockStatus = Literal["available", "active", "stale", "malformed"]


class SessionLockExistsError(RuntimeError):
    def __init__(self, inspection: SessionLockInspection) -> None:
        super().__init__(f"session lock already exists: {inspection.status}")
        self.inspection = inspection


@dataclass(frozen=True, slots=True)
class SessionLockInfo:
    lock_id: str
    pid: int
    hostname: str
    username: str | None
    started_at_utc: str
    dataset_id: str
    dataset_root: str
    workspace_root: str | None

    @classmethod
    def current(
        cls,
        *,
        dataset_id: str,
        dataset_root: Path,
        workspace_root: Path | None,
    ) -> SessionLockInfo:
        try:
            username = getpass.getuser()
        except (OSError, KeyError):
            username = None
        return cls(
            lock_id=uuid4().hex,
            pid=os.getpid(),
            hostname=socket.gethostname(),
            username=username,
            started_at_utc=utc_now_iso(),
            dataset_id=dataset_id,
            dataset_root=str(Path(dataset_root).resolve()),
            workspace_root=str(Path(workspace_root).resolve()) if workspace_root else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "lock_id": self.lock_id,
            "pid": self.pid,
            "hostname": self.hostname,
            "username": self.username,
            "started_at_utc": self.started_at_utc,
            "dataset_id": self.dataset_id,
            "dataset_root": self.dataset_root,
            "workspace_root": self.workspace_root,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SessionLockInfo:
        info = cls(
            lock_id=str(data["lock_id"]),
            pid=int(data["pid"]),
            hostname=str(data["hostname"]),
            username=str(data["username"]) if data.get("username") is not None else None,
            started_at_utc=str(data["started_at_utc"]),
            dataset_id=str(data["dataset_id"]),
            dataset_root=str(data["dataset_root"]),
            workspace_root=(
                str(data["workspace_root"])
                if data.get("workspace_root") is not None
                else None
            ),
        )
        if not info.lock_id or info.pid <= 0 or not info.hostname or not info.dataset_id:
            raise ValueError("session lock has invalid required fields")
        return info


@dataclass(frozen=True, slots=True)
class SessionLockInspection:
    status: LockStatus
    info: SessionLockInfo | None = None
    error: str | None = None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SessionLock:
    """Dataset edit-session lock with stale detection and ownership-safe release."""

    def __init__(
        self,
        annotation_dir: Path,
        *,
        pid_checker: Callable[[int], bool] = _pid_is_running,
    ) -> None:
        self.path = Path(annotation_dir) / ".session.lock"
        self._pid_checker = pid_checker
        self._owned: SessionLockInfo | None = None

    def inspect(self) -> SessionLockInspection:
        if not self.path.is_file():
            return SessionLockInspection("available")
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
            if not isinstance(data, Mapping):
                raise ValueError("session lock root must be an object")
            info = SessionLockInfo.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            return SessionLockInspection("malformed", error=str(exc))

        if info.hostname != socket.gethostname():
            return SessionLockInspection("active", info=info)
        status: LockStatus = "active" if self._pid_checker(info.pid) else "stale"
        return SessionLockInspection(status, info=info)

    def acquire(self, info: SessionLockInfo, *, force: bool = False) -> None:
        inspection = self.inspect()
        if inspection.status != "available" and not force:
            raise SessionLockExistsError(inspection)
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
                raise SessionLockExistsError(self.inspect()) from exc
        self._owned = info

    @staticmethod
    def _write(path: Path, info: SessionLockInfo, *, exclusive: bool) -> None:
        mode = "x" if exclusive else "w"
        with path.open(mode, encoding="utf-8", newline="\n") as stream:
            json.dump(info.to_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

    def release(self) -> bool:
        if self._owned is None:
            return False
        inspection = self.inspect()
        if inspection.info is None or inspection.info.lock_id != self._owned.lock_id:
            self._owned = None
            return False
        self.path.unlink()
        self._owned = None
        return True

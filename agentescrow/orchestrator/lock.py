"""A single-instance guard for the database.

The job runner, per-job locks, rate limiter and live streams are in-process, so two servers sharing one database would
race each other on money movements. The guard makes that mistake loud: the second server refuses to start.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class InstanceLockError(RuntimeError):
    """Another AgentEscrow server already holds the lock."""


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+")  # noqa: SIM115 - held for the life of the process
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - Windows
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            handle.close()
            raise InstanceLockError(
                f"Another AgentEscrow server is already using {self._path.parent}. Stop it first, or set SINGLE_INSTANCE=false "
                "if you are certain they use different databases."
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._handle = handle
        logger.info("Instance lock acquired (%s)", self._path)

    def release(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

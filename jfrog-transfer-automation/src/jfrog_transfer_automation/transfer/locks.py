from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import portalocker


@dataclass
class RunLock:
    lock_path: Path
    _handle: Optional[portalocker.Lock] = None

    def acquire(self) -> bool:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock = portalocker.Lock(str(self.lock_path), timeout=0)
        try:
            lock.acquire()
        except portalocker.exceptions.LockException:
            return False
        self._handle = lock
        return True

    def release(self) -> None:
        if self._handle:
            self._handle.release()
            self._handle = None

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
            # Try to remove the lock file after release (it may remain from portalocker)
            # Only remove if we successfully released it and the file exists
            try:
                if self.lock_path.exists():
                    self.lock_path.unlink()
            except (OSError, PermissionError):
                # Ignore errors - file might be locked by another process or already deleted
                # This is safe to ignore as the lock is already released
                pass

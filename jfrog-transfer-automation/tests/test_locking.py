from pathlib import Path

from jfrog_transfer_automation.transfer.locks import RunLock


def test_lock_exclusive(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    lock_a = RunLock(lock_path)
    lock_b = RunLock(lock_path)

    assert lock_a.acquire() is True
    assert lock_b.acquire() is False
    lock_a.release()
    assert lock_b.acquire() is True

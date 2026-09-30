"""Regression tests for single_command mode's monitored (non-blocking) transfer.

Prior to this fix, single_command mode ran ``jf rt transfer-files`` as a
blocking ``subprocess.run(capture_output=True)`` call: raw CLI output was
never written to disk, ``schedule.end_time`` was not enforced while the
call was blocked, and there was no stuck-transfer detection/restart (unlike
``per_repo`` mode). These tests lock in the fix: single_command now launches
the transfer as a background process and monitors it, mirroring the
per_repo pattern.
"""
import time
from typing import Optional

from jfrog_transfer_automation.config.model import AppConfig, JFrogConfig, ReportConfig, TransferConfig
from jfrog_transfer_automation.jfrog.cli import JFrogCLI
from jfrog_transfer_automation.transfer.runner import TransferRunner


class FakeProc:
    """Minimal stand-in for subprocess.Popen, driven by a list of poll() results."""

    def __init__(self, poll_sequence):
        self._poll_sequence = list(poll_sequence)
        self.pid = 12345
        self.killed = False

    def poll(self) -> Optional[int]:
        if self._poll_sequence:
            return self._poll_sequence.pop(0)
        return None

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout=None) -> None:
        return None


def _make_runner(monkeypatch, fake_procs, transfer_overrides=None):
    """Build a TransferRunner with subprocess/thread-adjustment stubbed out.

    ``fake_procs`` is consumed one-per-call to ``start_transfer_background``
    (a fresh FakeProc is returned each time, so restarts get a new process).
    """
    overrides = dict(
        include_repos_inline=["repo-a", "repo-b"],
        mode="single_command",
        skip_prechecks=True,
        poll_interval_seconds=0,  # don't actually sleep in tests
        stuck_timeout_seconds=600,
    )
    if transfer_overrides:
        overrides.update(transfer_overrides)

    config = AppConfig(
        jfrog=JFrogConfig(source_server_id="src", target_server_id="dst"),
        transfer=TransferConfig(**overrides),
        report=ReportConfig(),
    )
    runner = TransferRunner(config, JFrogCLI())

    # _adjust_threads() shells out to `jf rt transfer-settings`; not relevant here.
    monkeypatch.setattr(runner, "_adjust_threads", lambda *a, **kw: None)

    procs = list(fake_procs)

    def fake_start_transfer_background(repos, cli_home_dir=None, log_fh=None, active_count=0):
        return procs.pop(0)

    monkeypatch.setattr(runner, "start_transfer_background", fake_start_transfer_background)
    return runner


def test_single_command_writes_raw_log_and_completes(tmp_path, monkeypatch) -> None:
    """Normal completion: exit code 0 -> status completed, log file created."""
    proc = FakeProc(poll_sequence=[None, 0])
    runner = _make_runner(monkeypatch, [proc])

    run_dir = tmp_path / "run1"
    run_dir.mkdir()
    result = runner.run_and_monitor(run_dir)

    assert result.status == "completed"
    log_file = run_dir / "logs" / "transfer.log"
    assert log_file.exists(), "single_command mode must write raw CLI output to logs/transfer.log"


def test_single_command_nonzero_exit_returns_partial_without_raising(tmp_path, monkeypatch) -> None:
    """A failed transfer must return status='partial', not raise an uncaught exception."""
    proc = FakeProc(poll_sequence=[7])
    runner = _make_runner(monkeypatch, [proc])

    run_dir = tmp_path / "run2"
    run_dir.mkdir()
    result = runner.run_and_monitor(run_dir)

    assert result.status == "partial"
    assert "exit code 7" in result.message


def test_single_command_end_time_kills_process_mid_transfer(tmp_path, monkeypatch) -> None:
    """schedule.end_time must be enforced even while the transfer is still running."""
    proc = FakeProc(poll_sequence=[None] * 50)  # never exits on its own
    runner = _make_runner(monkeypatch, [proc])
    monkeypatch.setattr(runner, "stop", lambda *a, **kw: "stopped")

    run_dir = tmp_path / "run3"
    run_dir.mkdir()
    result = runner.run_and_monitor(run_dir, end_time=time.time() - 1)  # already past cutoff

    assert result.status == "completed"
    assert "end_time" in result.message
    assert proc.killed, "process must be killed when end_time is reached"


def test_single_command_stop_requested_returns_stopped(tmp_path, monkeypatch) -> None:
    """A user-invoked stop() must interrupt single_command mode too."""
    proc = FakeProc(poll_sequence=[None] * 50)
    runner = _make_runner(monkeypatch, [proc])

    run_dir = tmp_path / "run4"
    run_dir.mkdir()
    result = runner.run_and_monitor(run_dir, stop_requested=lambda: True)

    assert result.status == "stopped"
    assert proc.killed


def test_single_command_stuck_transfer_restarts_then_partial(tmp_path, monkeypatch) -> None:
    """A stalled transfer (no log activity) must restart up to 3 times, then give up."""
    procs = [FakeProc(poll_sequence=[None] * 100) for _ in range(4)]  # initial + 3 restarts
    runner = _make_runner(
        monkeypatch, procs, transfer_overrides={"stuck_timeout_seconds": 0},
    )

    run_dir = tmp_path / "run5"
    run_dir.mkdir()
    result = runner.run_and_monitor(run_dir)

    assert result.status == "partial"
    assert "stuck" in result.message.lower()
    assert all(p.killed for p in procs[:-1]), "all restarted processes must have been killed"

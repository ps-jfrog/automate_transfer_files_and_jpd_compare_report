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
    """Minimal stand-in for subprocess.Popen, driven by a list of poll() results.

    ``stdout_lines`` feeds the log-demultiplexer thread (see
    ``_demux_single_command_output``) — a real Popen's stdout would block
    waiting for more output, but a plain iterable is fine here since the
    thread just needs *something* iterable to drain without hanging.
    """

    def __init__(self, poll_sequence, stdout_lines=None):
        self._poll_sequence = list(poll_sequence)
        self.pid = 12345
        self.killed = False
        self.stdout = iter(stdout_lines or [])

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


def test_single_command_demuxes_per_repo_logs(tmp_path, monkeypatch) -> None:
    """The combined stream must be split into logs/<repo>.log by CLI phase markers.

    Repos are transferred sequentially by the real JFrog CLI, and its raw
    output includes markers like "for repo 'X'" / "repository 'X'" at each
    repo's phase boundaries. The demultiplexer thread watches for these to
    route lines to the correct per-repo file, in addition to always writing
    everything to the combined logs/transfer.log.
    """
    stdout_lines = [
        "12:00:00 [Info] Checking connectivity...\n",
        "12:00:01 [Debug] Getting repository 'repo-a' details ...\n",
        "12:00:01 [Info] Updating repository 'repo-a'...\n",
        "12:00:02 [Info] ========== Running 'Files Diff Handling Phase' for repo 'repo-a'... ==========\n",
        "12:00:03 [Info] Some repo-a detail line\n",
        "12:00:04 [Info] ========== Done running 'Files Diff Handling Phase' for repo 'repo-a'. ==========\n",
        "12:00:05 [Debug] Getting repository 'repo-b' details ...\n",
        "12:00:05 [Info] ========== Running 'Files Diff Handling Phase' for repo 'repo-b'... ==========\n",
        "12:00:06 [Info] Some repo-b detail line\n",
        "12:00:07 [Info] ========== Done running 'Files Diff Handling Phase' for repo 'repo-b'. ==========\n",
        "12:00:08 [Info] Files transfer is complete!\n",
    ]
    proc = FakeProc(poll_sequence=[None, 0], stdout_lines=stdout_lines)
    runner = _make_runner(monkeypatch, [proc])

    run_dir = tmp_path / "run6"
    run_dir.mkdir()
    result = runner.run_and_monitor(run_dir)

    assert result.status == "completed"

    combined = (run_dir / "logs" / "transfer.log").read_text()
    for line in stdout_lines:
        assert line in combined, "combined log must always contain every line"

    repo_a_log = (run_dir / "logs" / "repo-a.log").read_text()
    assert "Some repo-a detail line" in repo_a_log
    assert "Some repo-b detail line" not in repo_a_log
    # Preamble (before any repo marker) is job-wide, not repo-a's.
    assert "Checking connectivity" not in repo_a_log

    repo_b_log = (run_dir / "logs" / "repo-b.log").read_text()
    assert "Some repo-b detail line" in repo_b_log
    assert "Some repo-a detail line" not in repo_b_log
    # Once repo-b's marker starts, later lines with no marker stay with repo-b.
    assert "Files transfer is complete!" in repo_b_log

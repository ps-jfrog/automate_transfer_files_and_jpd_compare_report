from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from jfrog_transfer_automation.config.loader import apply_env_overrides, load_config
from jfrog_transfer_automation.jfrog.artifactory_api import ArtifactoryClient
from jfrog_transfer_automation.jfrog.auth import extract_cli_config
from jfrog_transfer_automation.jfrog.cli import JFrogCLI
from jfrog_transfer_automation.logging.setup import setup_logging
from jfrog_transfer_automation.notify.emailer import send_email
from jfrog_transfer_automation.notify.webhook import post_webhook
from jfrog_transfer_automation.report.generator import generate_report
from jfrog_transfer_automation.transfer.locks import RunLock
from jfrog_transfer_automation.transfer.runner import TransferRunner
from jfrog_transfer_automation.util.time import ScheduleWindow, get_missed_windows, next_window, parse_hhmm, sleep_seconds_until


def parse_args() -> argparse.Namespace:
    # Create a parent parser with common arguments shared by all subcommands
    # This allows --config to be used AFTER the subcommand
    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--config", required=True, help="Path to config file")
    parent_parser.add_argument("--verbose", action="store_true")
    
    parser = argparse.ArgumentParser(prog="jfrog-transfer-automation")
    # Also allow --config at top level (before subcommand) for convenience
    parser.add_argument("--config", required=False, help="Path to config file (can also be specified after subcommand)")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be executed without running")
    parser.add_argument("--background", action="store_true", help="Run in background (detach from terminal)")

    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("validate", parents=[parent_parser])
    
    run_once_parser = subparsers.add_parser("run-once", parents=[parent_parser])
    run_once_parser.add_argument("--background", action="store_true", help="Run in background")
    run_once_parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    
    subparsers.add_parser("status", parents=[parent_parser])
    
    subparsers.add_parser("stop", parents=[parent_parser])
    
    resume_parser = subparsers.add_parser("resume", parents=[parent_parser])
    resume_parser.add_argument("--background", action="store_true", help="Run in background")
    resume_parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    
    subparsers.add_parser("report", parents=[parent_parser])
    
    subparsers.add_parser("scheduler", parents=[parent_parser])
    
    monitor_parser = subparsers.add_parser("monitor", parents=[parent_parser])
    monitor_parser.add_argument("--interval", type=int, default=10, help="Monitor interval in seconds (default: 10)")
    
    simulate_parser = subparsers.add_parser("simulate-missed", parents=[parent_parser])
    simulate_parser.add_argument("--days-ago", type=int, default=2, help="Simulate last run N days ago (default: 2)")
    
    update_threads_parser = subparsers.add_parser("update-threads", parents=[parent_parser],
        help="Update transfer thread count (reads from config or --threads override)")
    update_threads_parser.add_argument("--threads", type=int, default=None,
        help="Thread count override (default: use transfer.threads from config)")

    subparsers.add_parser("clear-lock", parents=[parent_parser],
        help="Remove stale lock file and reset run state after a crash")

    args = parser.parse_args()
    
    # Ensure config is set (required by subcommands via parent_parser)
    # When using parents, argparse merges the namespaces, so args.config should be set
    # if provided either before or after the subcommand
    if not hasattr(args, 'config') or not args.config:
        parser.error("the following arguments are required: --config")
    
    return args


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _run_base(config) -> Path:
    """Resolve the base output directory from config."""
    return Path(config.report.output_dir).expanduser().resolve()


def _run_dir(base_dir: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = Path(base_dir).expanduser().resolve() / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _write_current_run(run_base: Path, payload: dict) -> None:
    run_base.mkdir(parents=True, exist_ok=True)
    (run_base / "current_run.json").write_text(json.dumps(payload, indent=2))


def _read_current_run(run_base: Path) -> dict | None:
    current = run_base / "current_run.json"
    if current.exists():
        return json.loads(current.read_text())
    return None


def _get_last_successful_run_time(run_base: Path) -> datetime | None:
    """Get the timestamp of the last successful run."""
    current = _read_current_run(run_base)
    if current and current.get("status") == "completed" and current.get("ended_at"):
        return datetime.fromtimestamp(current["ended_at"], tz=timezone.utc)
    
    # Also check completed runs in run directories
    run_dirs = sorted(run_base.glob("20*"), reverse=True)  # timestamped dirs
    for run_dir in run_dirs[:10]:  # Check last 10 runs
        summary = run_dir / "summary.json"
        if summary.exists():
            try:
                data = json.loads(summary.read_text())
                if data.get("status") == "completed" and data.get("ended_at"):
                    return datetime.fromtimestamp(data["ended_at"], tz=timezone.utc)
            except (json.JSONDecodeError, KeyError):
                continue
    
    return None


def _write_last_run_time(run_base: Path, timestamp: float) -> None:
    """Write last run time to a tracking file."""
    (run_base / "last_run_time.json").write_text(
        json.dumps({"last_run_time": timestamp}, indent=2)
    )


def _write_next_scheduled_run(run_base: Path, window: ScheduleWindow) -> None:
    """Write next scheduled run time to a tracking file."""
    (run_base / "next_scheduled_run.json").write_text(
        json.dumps({
            "next_run_start": window.start.isoformat(),
            "next_run_end": window.end.isoformat() if window.end else None,
        }, indent=2)
    )


def _end_timestamp(config) -> float | None:
    if not config.schedule.end_time:
        return None
    zone = ZoneInfo(config.schedule.timezone)
    now = datetime.now(tz=zone)
    end_time = parse_hhmm(config.schedule.end_time)
    end_dt = datetime.combine(now.date(), end_time, zone)
    if end_dt <= now:
        end_dt += timedelta(days=1)
    return end_dt.timestamp()


def _resolve_clients(config) -> tuple[ArtifactoryClient, ArtifactoryClient]:
    import logging
    logger = logging.getLogger("jfrog_transfer_automation")
    
    logger.debug("=== _resolve_clients: Starting ===")
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)

    for label, server_id in [
        ("source", config.jfrog.source_server_id),
        ("target", config.jfrog.target_server_id),
    ]:
        url = getattr(config.jfrog, f"{label}_url")
        token = getattr(config.jfrog, f"{label}_access_token")
        if not url or not token:
            logger.debug(f"Extracting {label} server config for: {server_id}")
            creds = extract_cli_config(jf_cli, server_id)
            if not url:
                setattr(config.jfrog, f"{label}_url", creds.url)
            if not token:
                setattr(config.jfrog, f"{label}_access_token", creds.access_token)
            logger.debug(f"{label.title()} server URL: {getattr(config.jfrog, f'{label}_url')}")
        else:
            logger.debug(f"{label.title()} URL and token already configured")

    def _make_client(label: str) -> ArtifactoryClient:
        return ArtifactoryClient(
            base_url=getattr(config.jfrog, f"{label}_url"),
            access_token=getattr(config.jfrog, f"{label}_access_token"),
            verify_ssl=config.jfrog.verify_ssl,
            timeout_seconds=config.jfrog.timeout_seconds,
            storage_calculation_wait_seconds=config.report.storage_calculation_wait_seconds,
        )

    logger.debug("Creating ArtifactoryClient instances...")
    result = _make_client("source"), _make_client("target")
    logger.debug("=== _resolve_clients: Completed ===")
    return result


def _run_in_background(config_path: str, verbose: bool, dry_run: bool, command: str = "run-once") -> int:
    """Run the transfer in background by spawning a detached process."""
    if dry_run:
        print("Would run in background (detached from terminal)")
        return 0
    
    # Get the current script/executable path
    script_args = [sys.executable, "-m", "jfrog_transfer_automation.cli.main", 
                   "--config", config_path, command]
    if verbose:
        script_args.append("--verbose")
    
    # On Windows, use CREATE_NEW_PROCESS_GROUP and DETACHED_PROCESS
    # On Unix, use os.fork() or subprocess with proper flags
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        process = subprocess.Popen(
            script_args,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Started background process with PID: {process.pid}")
    else:
        pid = os.fork()
        if pid == 0:
            os.setsid()
            process = subprocess.Popen(
                script_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            os._exit(0)
        else:
            print(f"Started background process with PID: {pid}")
    
    return 0


def _notify(config, report_path: Path, logger) -> None:
    try:
        if config.notify.method == "email":
            send_email(
                config.notify.email,
                subject="JFrog Transfer Report",
                body=f"Report available at: {report_path}",
            )
        elif config.notify.method == "webhook":
            post_webhook(
                config.notify.webhook.url,
                payload={"text": "JFrog Transfer Report", "path": str(report_path)},
                headers=config.notify.webhook.headers,
            )
    except Exception as exc:
        logger.error("Notification failed: %s", exc)


def _generate_report_and_notify(config, run_dir: Path, logger) -> None:
    """Generate the comparison report and send notifications."""
    source_client, target_client = _resolve_clients(config)
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    result = generate_report(
        source_client,
        target_client,
        run_dir / "reports",
        config.report.repo_type,
        detailed_comparison=config.report.detailed_comparison,
        repos_file_for_comparison=config.report.repos_file_for_comparison,
        enable_aql_queries=config.report.enable_aql_queries,
        source_server_id=config.jfrog.source_server_id,
        target_server_id=config.jfrog.target_server_id,
        jf_cli=jf_cli,
    )
    logger.info("Report generated: %s", result.report_path)
    _notify(config, result.report_path, logger)


def _print_status_results(results: dict) -> None:
    """Print per-CLI-home status results with consistent formatting."""
    for name, status_text in results.items():
        if len(results) > 1:
            print(f"\n  [{name}]")
            for line in (status_text or "").splitlines():
                print(f"    {line}")
        else:
            print(status_text or "(no output)")


def _clear_stale_running_status(run_base: Path, logger) -> None:
    """Clear a stale 'running' status when the lock was successfully acquired."""
    current = _read_current_run(run_base)
    if not current or current.get('status') != 'running':
        return

    started_at = current.get('started_at')
    if not started_at:
        return

    started_dt = datetime.fromtimestamp(started_at, tz=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - started_dt).total_seconds() / 3600

    if age_hours > 24:
        logger.warning(f"Found stale 'running' status (started {age_hours:.1f} hours ago). Clearing it.")
        _write_current_run(run_base, {"status": "cleared_stale", "cleared_at": time.time()})
    else:
        lock_file = run_base / ".lock"
        if not lock_file.exists():
            logger.warning("Found 'running' status but no lock file. Clearing stale status.")
            _write_current_run(run_base, {"status": "cleared_stale", "cleared_at": time.time()})
        else:
            logger.warning(f"Found 'running' status (started {age_hours:.1f} hours ago) but lock was acquired. This may indicate a stale status.")


def _execute_transfer(
    config,
    verbose: bool,
    dry_run: bool = False,
    background: bool = False,
    config_path: str = "",
    command: str = "run-once",
) -> int:
    """Core transfer execution shared by run-once and resume."""
    if background:
        return _run_in_background(config_path, verbose, dry_run, command=command)

    run_dir = _run_dir(config.report.output_dir)
    logger = setup_logging(run_dir, verbose)

    run_base = _run_base(config)
    lock = RunLock(run_base / ".lock")
    if not lock.acquire():
        current = _read_current_run(run_base)
        if current and current.get('started_at'):
            started_dt = datetime.fromtimestamp(current['started_at'], tz=timezone.utc)
            logger.info(f"Run in progress (started at {started_dt.strftime('%Y-%m-%d %H:%M:%S')}). Skipping.")
        elif current:
            logger.info("Run in progress (status: {}). Skipping.".format(current.get('status', 'unknown')))
        else:
            logger.info("Run in progress (lock held by another process). Skipping.")
        return 1

    if command == "run-once":
        _clear_stale_running_status(run_base, logger)
    logger.debug("Lock acquired successfully")

    try:
        run_payload: dict = {"status": "running", "run_dir": str(run_dir)}
        if command == "resume":
            run_payload["resumed_at"] = time.time()
        else:
            run_payload["started_at"] = time.time()
        _write_current_run(run_base, run_payload)

        transfer = TransferRunner(config, JFrogCLI(config.jfrog.jfrog_cli_path))
        end_time = _end_timestamp(config)

        def _check_stop() -> bool:
            current = _read_current_run(run_base)
            return bool(current and current.get("status") == "stopped")

        transfer_result = transfer.run_and_monitor(
            run_dir, end_time=end_time, dry_run=dry_run, stop_requested=_check_stop,
        )

        if not dry_run:
            logger.info(
                "Transfer %s in %.1fs",
                transfer_result.status,
                transfer_result.ended_at - transfer_result.started_at,
            )

            if transfer_result.status == "stopped":
                logger.info("Transfer was stopped by user — skipping report generation")
            elif config.report.enabled:
                _generate_report_and_notify(config, run_dir, logger)

            final_status = transfer_result.status if transfer_result.status in ("stopped", "partial") else "completed"
            _write_current_run(
                run_base,
                {"status": final_status, "ended_at": time.time(), "run_dir": str(run_dir)},
            )
            if command == "run-once" and final_status != "stopped":
                _write_last_run_time(run_base, time.time())
        else:
            logger.info("Dry run completed - no actual transfer executed")

        return 0
    finally:
        lock.release()


# ---------------------------------------------------------------------------
# CLI command handlers
# ---------------------------------------------------------------------------

def cmd_validate(config) -> int:
    """Validate configuration and JFrog CLI setup."""
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    
    if not config.schedule.start_time:
        raise RuntimeError("schedule.start_time is required in config")
    
    if not config.jfrog.source_server_id:
        raise RuntimeError("jfrog.source_server_id is required in config")
    if not config.jfrog.target_server_id:
        raise RuntimeError("jfrog.target_server_id is required in config")
    
    for label, server_id in [
        ("source", config.jfrog.source_server_id),
        ("target", config.jfrog.target_server_id),
    ]:
        print(f"Validating {label} server: {server_id}")
        try:
            creds = extract_cli_config(jf_cli, server_id)
            print(f"  ✓ {label.title()} server configured: {creds.url}")
        except RuntimeError as e:
            print(f"  ✗ {label.title()} server validation failed")
            raise RuntimeError(f"{label.title()} server validation failed: {e}")
    
    print("\n✓ Configuration validation successful!")
    return 0


def cmd_run_once(config, verbose: bool, dry_run: bool = False, background: bool = False, config_path: str = "") -> int:
    return _execute_transfer(config, verbose, dry_run, background, config_path, command="run-once")


def cmd_status(config) -> int:
    """Check transfer status, querying each per-repo CLI home when applicable."""
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    runner = TransferRunner(config, jf_cli)

    print("JFrog Transfer Status:")
    _print_status_results(runner.status_all())

    run_base = _run_base(config)
    current = _read_current_run(run_base)
    if current:
        print("\nCurrent Run Info:")
        print(json.dumps(current, indent=2))
    else:
        print("\nNo current run information found.")

    return 0


def cmd_stop(config) -> int:
    """Stop running transfers, sending stop to each per-repo CLI home when applicable."""
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    runner = TransferRunner(config, jf_cli)

    print("Stopping transfer...")
    results = runner.stop_all()

    for name, output in results.items():
        if len(results) > 1:
            print(f"  [{name}] {output}")
        else:
            print(output)

    run_base = _run_base(config)
    current = _read_current_run(run_base)
    if current:
        current["status"] = "stopped"
        current["stopped_at"] = time.time()
        _write_current_run(run_base, current)
        print("Run status updated to 'stopped'")

    return 0


def cmd_clear_lock(config) -> int:
    """Remove a stale lock file and reset current_run.json after a crash.

    Attempts to acquire the lock first.  If successful the lock is not truly
    held by another process and it is safe to clean up.  If the lock cannot
    be acquired, another run is genuinely active and the user is warned.
    """
    run_base = _run_base(config)
    lock_path = run_base / ".lock"
    current_run_path = run_base / "current_run.json"

    lock = RunLock(lock_path)
    if not lock.acquire():
        print("WARNING: The lock is currently held by another process.")
        print("A transfer may still be running. Use 'stop' first if you want to stop it.")
        return 1

    # Lock acquired — no process is genuinely using it, so it's stale
    lock.release()

    removed_any = False

    if lock_path.exists():
        lock_path.unlink()
        print(f"  ✓ Removed stale lock file: {lock_path}")
        removed_any = True

    current = None
    if current_run_path.exists():
        current = _read_current_run(run_base)
        if current and current.get("status") == "running":
            _write_current_run(run_base, {
                "status": "cleared_stale",
                "cleared_at": time.time(),
                "previous_status": current,
            })
            print(f"  ✓ Reset stale 'running' status in: {current_run_path}")
            removed_any = True
        else:
            print(f"  - current_run.json status is '{current.get('status') if current else 'N/A'}' (not stale)")

    if not removed_any:
        print("No stale lock or run state found. Nothing to clear.")
    else:
        print("\nStale state cleared. You can now run 'run-once' or 'scheduler' again.")

    return 0


def cmd_update_threads(config, threads: int | None = None) -> int:
    """Update transfer thread count across all relevant CLI homes.

    Re-reads the thread count from config (or uses --threads override) and
    applies it via 'jf rt transfer-settings' to the default CLI home and/or
    every per-repo isolated CLI home directory.  Safe to run while a transfer
    is in progress — changes take effect on the next transfer chunk.
    """
    thread_count = threads if threads is not None else config.transfer.threads
    strategy = config.transfer.jfrog_cli_home_strategy

    print(f"Updating transfer threads to {thread_count} (strategy: {strategy})")

    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    runner = TransferRunner(config, jf_cli)
    results = runner.update_threads(thread_count)

    if not results:
        print("No CLI homes found to update. Have you run a transfer yet?")
        return 1

    errors = 0
    for name, status in results.items():
        if status == "ok":
            print(f"  ✓ {name}: threads set to {thread_count}")
        else:
            print(f"  ✗ {name}: {status}")
            errors += 1

    if errors:
        print(f"\n{errors} CLI home(s) failed to update.")
        return 1

    print(f"\nSuccessfully updated threads to {thread_count} across {len(results)} CLI home(s).")
    return 0


def cmd_resume(config, verbose: bool, dry_run: bool = False, background: bool = False, config_path: str = "") -> int:
    """Resume a stopped transfer."""
    return _execute_transfer(config, verbose, dry_run, background, config_path, command="resume")


def cmd_monitor(config, interval: int = 10) -> int:
    """Monitor transfer progress continuously, querying per-repo CLI homes when applicable."""
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    runner = TransferRunner(config, jf_cli)
    run_base = _run_base(config)

    print(f"Monitoring transfer (interval: {interval}s). Press Ctrl+C to stop monitoring...")
    print("(Note: Transfer will continue running even if monitoring stops)\n")

    try:
        while True:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Transfer Status:")
            _print_status_results(runner.status_all())

            current = _read_current_run(run_base)
            if current:
                print("\nCurrent Run Info:")
                print(json.dumps(current, indent=2))

            print("\n" + "=" * 60 + "\n")

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nMonitoring stopped. Transfer continues in background.")
        return 0


def cmd_simulate_missed(config, verbose: bool, days_ago: int = 2) -> int:
    """Simulate a missed schedule scenario for testing catch_up_if_missed."""
    run_base = _run_base(config)
    logger = setup_logging(run_base, verbose)
    
    # Create a fake last run time
    fake_last_run = datetime.now(timezone.utc) - timedelta(days=days_ago)
    logger.info(f"Simulating last run time: {fake_last_run} ({days_ago} days ago)")
    
    # Write fake last run time
    _write_last_run_time(run_base, fake_last_run.timestamp())
    
    # Check for missed windows
    now = datetime.now(timezone.utc)
    missed = get_missed_windows(
        fake_last_run,
        now,
        config.schedule.start_time,
        config.schedule.end_time,
        config.schedule.timezone,
    )
    
    if missed:
        logger.info(f"Found {len(missed)} missed schedule window(s):")
        for window in missed:
            logger.info(f"  - {window.start}")
        
        if config.schedule.catch_up_if_missed:
            logger.info("catch_up_if_missed is enabled. Running a single catch-up transfer "
                        f"to cover all {len(missed)} missed window(s)...")
            result = cmd_run_once(config, verbose)
            if result == 0:
                logger.info(f"Catch-up transfer completed successfully (covered {len(missed)} missed window(s))")
            else:
                logger.warning(f"Catch-up transfer returned non-zero exit code: {result}")
                logger.warning("This may be because the lock was held by another process (e.g., scheduler)")
        else:
            logger.info("catch_up_if_missed is disabled. Skipping missed runs.")
    else:
        logger.info("No missed windows found with current simulation.")
        logger.debug("This could mean:")
        logger.debug("  - The fake last run time is too recent")
        logger.debug("  - The schedule time hasn't occurred yet today")
        logger.debug("  - There's an issue with the missed windows calculation")
    
    return 0


def cmd_report(config, verbose: bool) -> int:
    run_dir = _run_dir(config.report.output_dir)
    logger = setup_logging(run_dir, verbose)
    _generate_report_and_notify(config, run_dir, logger)
    return 0


def cmd_scheduler(config, verbose: bool) -> int:
    run_base = _run_base(config)
    logger = setup_logging(run_base, verbose)

    # Handle catch-up if missed runs
    if config.schedule.catch_up_if_missed:
        last_run = _get_last_successful_run_time(run_base)
        if last_run:
            now = datetime.now(timezone.utc)
            missed = get_missed_windows(
                last_run,
                now,
                config.schedule.start_time,
                config.schedule.end_time,
                config.schedule.timezone,
            )
            if missed:
                logger.info(f"Found {len(missed)} missed schedule window(s):")
                for window in missed:
                    logger.info(f"  - {window.start}")
                logger.info("Running a single catch-up transfer to cover all missed windows...")
                cmd_run_once(config, verbose)

    if config.schedule.run_on_startup:
        cmd_run_once(config, verbose)

    while True:
        window = next_window(
            datetime.now(timezone.utc),
            config.schedule.start_time,
            config.schedule.end_time,
            config.schedule.timezone,
        )
        sleep_for = sleep_seconds_until(window.start)
        logger.info(f"Next scheduled run at {window.start} (in {sleep_for} seconds)")
        _write_next_scheduled_run(run_base, window)
        time.sleep(sleep_for)

        logger.info(f"Starting scheduled transfer at {window.start}")
        # cmd_run_once handles its own locking - if lock is held, it will skip and return 1
        result = cmd_run_once(config, verbose)
        if result != 0:
            # Lock was held - cmd_run_once already logged the reason
            # Wait a bit before recalculating to ensure we get the next window, not the same one
            time.sleep(1)
            continue


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    import logging
    logger = logging.getLogger("jfrog_transfer_automation")
    
    args = parse_args()
    logger.debug(f"=== main: Starting jfrog-transfer-automation ===")
    logger.debug(f"Command: {args.command}, Config: {args.config}, Verbose: {args.verbose}")
    
    logger.debug("Loading configuration...")
    config = apply_env_overrides(load_config(args.config))
    logger.debug("Configuration loaded successfully")
    
    command = args.command
    
    # Get dry_run and background from command-specific args or top-level args
    dry_run = getattr(args, "dry_run", False)
    background = getattr(args, "background", False)
    logger.debug(f"dry_run: {dry_run}, background: {background}")

    if command == "validate":
        return cmd_validate(config)
    if command == "run-once":
        return cmd_run_once(config, args.verbose, dry_run=dry_run, background=background, config_path=args.config)
    if command == "status":
        return cmd_status(config)
    if command == "stop":
        return cmd_stop(config)
    if command == "resume":
        return cmd_resume(config, args.verbose, dry_run=dry_run, background=background, config_path=args.config)
    if command == "monitor":
        interval = getattr(args, "interval", 10)
        return cmd_monitor(config, interval=interval)
    if command == "report":
        return cmd_report(config, args.verbose)
    if command == "scheduler":
        return cmd_scheduler(config, args.verbose)
    if command == "simulate-missed":
        days_ago = getattr(args, "days_ago", 2)
        return cmd_simulate_missed(config, args.verbose, days_ago=days_ago)
    if command == "update-threads":
        threads_override = getattr(args, "threads", None)
        return cmd_update_threads(config, threads=threads_override)
    if command == "clear-lock":
        return cmd_clear_lock(config)

    raise RuntimeError(f"Unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())

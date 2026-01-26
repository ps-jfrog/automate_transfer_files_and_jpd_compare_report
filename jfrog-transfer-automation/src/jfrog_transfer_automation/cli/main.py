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
from jfrog_transfer_automation.transfer.repo_list import load_repos
from jfrog_transfer_automation.util.time import get_missed_windows, next_window, parse_hhmm, sleep_seconds_until


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
    
    validate_parser = subparsers.add_parser("validate", parents=[parent_parser])
    
    run_once_parser = subparsers.add_parser("run-once", parents=[parent_parser])
    run_once_parser.add_argument("--background", action="store_true", help="Run in background")
    run_once_parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    
    status_parser = subparsers.add_parser("status", parents=[parent_parser])
    
    stop_parser = subparsers.add_parser("stop", parents=[parent_parser])
    
    resume_parser = subparsers.add_parser("resume", parents=[parent_parser])
    resume_parser.add_argument("--background", action="store_true", help="Run in background")
    resume_parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    
    report_parser = subparsers.add_parser("report", parents=[parent_parser])
    
    scheduler_parser = subparsers.add_parser("scheduler", parents=[parent_parser])
    
    monitor_parser = subparsers.add_parser("monitor", parents=[parent_parser])
    monitor_parser.add_argument("--interval", type=int, default=10, help="Monitor interval in seconds (default: 10)")
    
    simulate_parser = subparsers.add_parser("simulate-missed", parents=[parent_parser])
    simulate_parser.add_argument("--days-ago", type=int, default=2, help="Simulate last run N days ago (default: 2)")
    
    args = parser.parse_args()
    
    # Ensure config is set (required by subcommands via parent_parser)
    # When using parents, argparse merges the namespaces, so args.config should be set
    # if provided either before or after the subcommand
    if not hasattr(args, 'config') or not args.config:
        parser.error("the following arguments are required: --config")
    
    return args


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
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)

    if not config.jfrog.source_url or not config.jfrog.source_access_token:
        creds = extract_cli_config(jf_cli, config.jfrog.source_server_id)
        config.jfrog.source_url = config.jfrog.source_url or creds.url
        config.jfrog.source_access_token = (
            config.jfrog.source_access_token or creds.access_token
        )

    if not config.jfrog.target_url or not config.jfrog.target_access_token:
        creds = extract_cli_config(jf_cli, config.jfrog.target_server_id)
        config.jfrog.target_url = config.jfrog.target_url or creds.url
        config.jfrog.target_access_token = (
            config.jfrog.target_access_token or creds.access_token
        )

    source_client = ArtifactoryClient(
        base_url=config.jfrog.source_url,
        access_token=config.jfrog.source_access_token,
        verify_ssl=config.jfrog.verify_ssl,
        timeout_seconds=config.jfrog.timeout_seconds,
        storage_calculation_wait_seconds=config.report.storage_calculation_wait_seconds,
    )
    target_client = ArtifactoryClient(
        base_url=config.jfrog.target_url,
        access_token=config.jfrog.target_access_token,
        verify_ssl=config.jfrog.verify_ssl,
        timeout_seconds=config.jfrog.timeout_seconds,
        storage_calculation_wait_seconds=config.report.storage_calculation_wait_seconds,
    )
    return source_client, target_client


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
        # Windows background execution
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        process = subprocess.Popen(
            script_args,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"Started background process with PID: {process.pid}")
    else:
        # Unix background execution
        pid = os.fork()
        if pid == 0:
            # Child process
            os.setsid()
            process = subprocess.Popen(
                script_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            os._exit(0)
        else:
            # Parent process
            print(f"Started background process with PID: {pid}")
    
    return 0


def cmd_validate(config) -> int:
    """Validate configuration and JFrog CLI setup."""
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    
    # Validate schedule
    if not config.schedule.start_time:
        raise RuntimeError("schedule.start_time is required in config")
    
    # Validate server IDs
    if not config.jfrog.source_server_id:
        raise RuntimeError("jfrog.source_server_id is required in config")
    if not config.jfrog.target_server_id:
        raise RuntimeError("jfrog.target_server_id is required in config")
    
    # Validate JFrog CLI server configurations
    print(f"Validating source server: {config.jfrog.source_server_id}")
    try:
        source_creds = extract_cli_config(jf_cli, config.jfrog.source_server_id)
        print(f"  ✓ Source server configured: {source_creds.url}")
    except RuntimeError as e:
        print(f"  ✗ Source server validation failed")
        raise RuntimeError(f"Source server validation failed: {e}")
    
    print(f"Validating target server: {config.jfrog.target_server_id}")
    try:
        target_creds = extract_cli_config(jf_cli, config.jfrog.target_server_id)
        print(f"  ✓ Target server configured: {target_creds.url}")
    except RuntimeError as e:
        print(f"  ✗ Target server validation failed")
        raise RuntimeError(f"Target server validation failed: {e}")
    
    print("\n✓ Configuration validation successful!")
    return 0


def cmd_run_once(config, verbose: bool, dry_run: bool = False, background: bool = False, config_path: str = "") -> int:
    if background:
        return _run_in_background(config_path, verbose, dry_run)
    
    run_dir = _run_dir(config.report.output_dir)
    logger = setup_logging(run_dir, verbose)

    run_base = Path(config.report.output_dir).expanduser().resolve()
    lock = RunLock(run_base / ".lock")
    if not lock.acquire():
        logger.info("Run in progress. Skipping.")
        return 1

    try:
        _write_current_run(
            run_base,
            {"status": "running", "started_at": time.time(), "run_dir": str(run_dir)},
        )
        transfer = TransferRunner(config, JFrogCLI(config.jfrog.jfrog_cli_path))
        transfer_result = transfer.run_and_monitor(run_dir, end_time=_end_timestamp(config), dry_run=dry_run)
        
        if not dry_run:
            logger.info("Transfer completed in %.1fs", transfer_result.ended_at - transfer_result.started_at)

            if config.report.enabled:
                source_client, target_client = _resolve_clients(config)
                report_dir = run_dir / "reports"
                jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
                result = generate_report(
                    source_client,
                    target_client,
                    report_dir,
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

            _write_current_run(
                run_base,
                {"status": "completed", "ended_at": time.time(), "run_dir": str(run_dir)},
            )
            _write_last_run_time(run_base, time.time())
        else:
            logger.info("Dry run completed - no actual transfer executed")
        
        return 0
    finally:
        lock.release()


def cmd_status(config) -> int:
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    status = jf_cli.run(["rt", "transfer-files", "--status"])
    print("JFrog Transfer Status:")
    print(status.stdout or status.stderr)

    run_base = Path(config.report.output_dir).expanduser().resolve()
    current = _read_current_run(run_base)
    if current:
        print("\nCurrent Run Info:")
        print(json.dumps(current, indent=2))
    else:
        print("\nNo current run information found.")
    
    return 0


def cmd_stop(config) -> int:
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    result = jf_cli.run(["rt", "transfer-files", "--stop"])
    print("Stopping transfer...")
    print(result.stdout or result.stderr)
    
    run_base = Path(config.report.output_dir).expanduser().resolve()
    current = _read_current_run(run_base)
    if current:
        current["status"] = "stopped"
        current["stopped_at"] = time.time()
        _write_current_run(run_base, current)
        print("Run status updated to 'stopped'")
    
    return 0


def cmd_resume(config, verbose: bool, dry_run: bool = False, background: bool = False, config_path: str = "") -> int:
    """Resume a stopped transfer."""
    if background:
        return _run_in_background(config_path, verbose, dry_run, command="resume")
    
    run_dir = _run_dir(config.report.output_dir)
    logger = setup_logging(run_dir, verbose)
    
    run_base = Path(config.report.output_dir).expanduser().resolve()
    lock = RunLock(run_base / ".lock")
    if not lock.acquire():
        logger.info("Run in progress. Cannot resume while another run is active.")
        return 1
    
    try:
        repos = load_repos(
            config.transfer.include_repos_file,
            config.transfer.include_repos_inline,
        )
        
        transfer = TransferRunner(config, JFrogCLI(config.jfrog.jfrog_cli_path))
        
        if dry_run:
            logger.info("Dry run: Would resume transfer")
            transfer.resume(repos, dry_run=True)
            return 0
        
        logger.info("Resuming transfer...")
        transfer.resume(repos, dry_run=False)
        
        _write_current_run(
            run_base,
            {"status": "running", "resumed_at": time.time(), "run_dir": str(run_dir)},
        )
        
        # Monitor the transfer
        transfer_result = transfer.run_and_monitor(run_dir, end_time=_end_timestamp(config), dry_run=False)
        logger.info("Transfer completed in %.1fs", transfer_result.ended_at - transfer_result.started_at)
        
        if config.report.enabled:
            source_client, target_client = _resolve_clients(config)
            report_dir = run_dir / "reports"
            jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
            result = generate_report(
                source_client,
                target_client,
                report_dir,
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
        
        _write_current_run(
            run_base,
            {"status": "completed", "ended_at": time.time(), "run_dir": str(run_dir)},
        )
        
        return 0
    finally:
        lock.release()


def cmd_monitor(config, interval: int = 10) -> int:
    """Monitor transfer progress continuously."""
    jf_cli = JFrogCLI(config.jfrog.jfrog_cli_path)
    run_base = Path(config.report.output_dir).expanduser().resolve()
    
    print(f"Monitoring transfer (interval: {interval}s). Press Ctrl+C to stop monitoring...")
    print("(Note: Transfer will continue running even if monitoring stops)\n")
    
    try:
        while True:
            # Check JFrog transfer status
            status = jf_cli.run(["rt", "transfer-files", "--status"])
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Transfer Status:")
            print(status.stdout or status.stderr)
            
            # Check current run info
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
    run_base = Path(config.report.output_dir).expanduser().resolve()
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
            logger.info("catch_up_if_missed is enabled. Would run catch-up transfers.")
            lock = RunLock(run_base / ".lock")
            for window in missed:
                if lock.acquire():
                    try:
                        logger.info(f"Running catch-up for {window.start}")
                        cmd_run_once(config, verbose)
                    finally:
                        lock.release()
                else:
                    logger.warning("Lock held, skipping catch-up window")
        else:
            logger.info("catch_up_if_missed is disabled. Would skip missed runs.")
    else:
        logger.info("No missed windows found with current simulation.")
    
    return 0


def cmd_report(config, verbose: bool) -> int:
    run_dir = _run_dir(config.report.output_dir)
    logger = setup_logging(run_dir, verbose)
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
    return 0


def cmd_scheduler(config, verbose: bool) -> int:
    run_base = Path(config.report.output_dir).expanduser().resolve()
    lock = RunLock(run_base / ".lock")
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
                logger.info(f"Found {len(missed)} missed schedule window(s). Running catch-up...")
                for window in missed:
                    if lock.acquire():
                        try:
                            logger.info(f"Catching up missed run from {window.start}")
                            cmd_run_once(config, verbose)
                        finally:
                            lock.release()
                    else:
                        logger.warning("Lock held during catch-up, skipping missed window")

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
        time.sleep(sleep_for)

        if lock.acquire():
            lock.release()
            cmd_run_once(config, verbose)


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


def main() -> int:
    args = parse_args()
    config = apply_env_overrides(load_config(args.config))
    command = args.command
    
    # Get dry_run and background from command-specific args or top-level args
    dry_run = getattr(args, "dry_run", False)
    background = getattr(args, "background", False)

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

    raise RuntimeError(f"Unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())

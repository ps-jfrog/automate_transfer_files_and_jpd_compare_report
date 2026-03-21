from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from jfrog_transfer_automation.config.model import AppConfig
from jfrog_transfer_automation.jfrog.cli import JFrogCLI
from jfrog_transfer_automation.transfer.repo_list import load_repos

logger = logging.getLogger(__name__)


@dataclass
class TransferResult:
    status: str
    started_at: float
    ended_at: float
    repos: List[str]
    run_dir: Path
    message: Optional[str] = None


class TransferRunner:
    def __init__(self, config: AppConfig, jf_cli: JFrogCLI) -> None:
        self.config = config
        self.jf_cli = jf_cli

    def _include_repos_arg(self, repos: List[str]) -> str:
        return ";".join(repos)

    def _adjust_threads(
        self,
        thread_count: int,
        dry_run: bool = False,
        cli_home_dir: Optional[Path] = None,
    ) -> None:
        """Adjust transfer threads using non-interactive JFrog CLI.
        
        Uses 'jf rt transfer-settings' to set the thread count.
        This must be done before starting transfer-files.
        When cli_home_dir is provided, sets JFROG_CLI_HOME_DIR so the setting
        is applied to the correct (possibly isolated) CLI home.
        """
        logger.debug(f"=== _adjust_threads: Setting threads to {thread_count} (cli_home_dir={cli_home_dir}) ===")
        if dry_run:
            print(f"  Would set transfer threads to {thread_count} using: echo {thread_count} | {self.jf_cli.jfrog_cli_path} rt transfer-settings")
            if cli_home_dir:
                print(f"  With JFROG_CLI_HOME_DIR={cli_home_dir}")
            logger.debug("Dry run: Would adjust threads")
            return
        
        try:
            env = os.environ.copy()
            if cli_home_dir:
                env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)

            if sys.platform == "win32":
                cmd = f'echo {thread_count} | {self.jf_cli.jfrog_cli_path} rt transfer-settings'
                logger.debug(f"Windows: Executing: {cmd}")
                subprocess.run(cmd, shell=True, check=True, env=env)
            else:
                cmd = ['bash', '-c', f'echo {thread_count} | {self.jf_cli.jfrog_cli_path} rt transfer-settings']
                logger.debug(f"Unix: Executing: {' '.join(cmd)}")
                subprocess.run(cmd, check=True, env=env)
            logger.info(f"Set transfer threads to {thread_count} (cli_home_dir={cli_home_dir})")
            logger.debug("Thread adjustment completed successfully")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to set transfer threads to {thread_count}: {e}")
            logger.debug(f"Thread adjustment failed, but continuing (non-fatal)")

    def _build_transfer_args(self, repos: List[str]) -> List[str]:
        """Build the transfer-files command arguments.
        
        Command format: jf rt transfer-files [options] <source-server-id> <target-server-id>
        Server IDs must come AFTER all options.
        Note: Threads are set separately using 'jf rt transfer-settings', not as a command argument.
        """
        args = [
            "rt",
            "transfer-files",
            "--include-repos",
            self._include_repos_arg(repos),
        ]
        
        # Always include --ignore-state with explicit value (JFrog CLI requires this)
        ignore_state_value = str(self.config.transfer.ignore_state).lower()
        args.append(f"--ignore-state={ignore_state_value}")
        logger.debug(f"Adding ignore-state argument: --ignore-state={ignore_state_value} (from config: {self.config.transfer.ignore_state})")
        
        # Only include --filestore if it's True (presence of flag means enabled)
        if self.config.transfer.filestore:
            args.append("--filestore")
        
        # Server IDs come after all options
        args.append(self.config.jfrog.source_server_id)
        args.append(self.config.jfrog.target_server_id)
        
        return args

    def _get_cli_home_dir(self, repo: str, run_dir: Path) -> Optional[Path]:
        """Get isolated CLI home directory for a repo if strategy is per_repo_isolated.
        
        CLI homes are stored under <output_dir>/cli_homes/<repo>/ (persistent across runs)
        so that JFrog CLI transfer state is preserved for delta sync, while still giving
        each repo its own JFROG_CLI_HOME_DIR for concurrency safety.
        """
        if self.config.transfer.jfrog_cli_home_strategy == "per_repo_isolated":
            run_base = Path(self.config.report.output_dir).expanduser().resolve()
            repo_home = run_base / "cli_homes" / repo
            repo_home.mkdir(parents=True, exist_ok=True)
            self._bootstrap_cli_home(repo_home)
            return repo_home
        return None

    def _bootstrap_cli_home(self, cli_home_dir: Path) -> None:
        """Import source and target server configs into an isolated CLI home if not already present.
        
        Exports server configurations from the default CLI home (~/.jfrog) and imports
        them into the isolated directory so that jf rt transfer-files can find the
        configured server IDs.
        """
        env = os.environ.copy()
        env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)

        # Check if source server is already configured in this home
        check = self.jf_cli.run(
            ["c", "show", self.config.jfrog.source_server_id], env=env
        )
        if check.returncode == 0:
            logger.debug(f"CLI home {cli_home_dir} already bootstrapped, skipping")
            return

        logger.info(f"Bootstrapping CLI home: {cli_home_dir}")
        for server_id in [
            self.config.jfrog.source_server_id,
            self.config.jfrog.target_server_id,
        ]:
            # Export from default home (no JFROG_CLI_HOME_DIR override)
            export_result = self.jf_cli.run(["c", "export", server_id])
            if export_result.returncode != 0 or not export_result.stdout:
                raise RuntimeError(
                    f"Failed to export server config for '{server_id}' from default CLI home. "
                    f"Ensure 'jf c show {server_id}' works. Error: {export_result.stderr}"
                )

            # Import into isolated home
            import_result = self.jf_cli.run(
                ["c", "import", export_result.stdout.strip()], env=env
            )
            if import_result.returncode != 0:
                raise RuntimeError(
                    f"Failed to import server config for '{server_id}' into {cli_home_dir}. "
                    f"Error: {import_result.stderr}"
                )
            logger.info(f"Imported server config '{server_id}' into {cli_home_dir}")

    def _get_all_cli_homes(self) -> List[Path]:
        """Return all per-repo isolated CLI home directories that exist on disk."""
        cli_homes_base = Path(self.config.report.output_dir).expanduser().resolve() / "cli_homes"
        if not cli_homes_base.is_dir():
            return []
        return sorted(d for d in cli_homes_base.iterdir() if d.is_dir())

    def _is_per_repo_isolated(self) -> bool:
        return self.config.transfer.jfrog_cli_home_strategy == "per_repo_isolated"

    def update_threads(self, thread_count: int) -> dict:
        """Apply thread count to all relevant CLI homes (default and/or per-repo isolated).

        Discovers isolated CLI homes and applies the setting to each one.
        Returns a summary dict with per-home results.
        """
        results: dict = {}

        if self._is_per_repo_isolated():
            cli_homes = self._get_all_cli_homes()
            if not cli_homes:
                logger.warning("No cli_homes directories found")
            for repo_dir in cli_homes:
                try:
                    self._adjust_threads(thread_count, cli_home_dir=repo_dir)
                    results[repo_dir.name] = "ok"
                except Exception as e:
                    results[repo_dir.name] = f"error: {e}"
        else:
            try:
                self._adjust_threads(thread_count)
                results["default"] = "ok"
            except Exception as e:
                results["default"] = f"error: {e}"

        return results

    def _check_stuck(self, log_file: Path) -> bool:
        """Check if transfer is stuck by examining log file modification time."""
        if not log_file.exists():
            return False
        
        mtime = log_file.stat().st_mtime
        elapsed = time.time() - mtime
        return elapsed > self.config.transfer.stuck_timeout_seconds

    def start_transfer(
        self, 
        repos: List[str], 
        dry_run: bool = False,
        cli_home_dir: Optional[Path] = None,
    ) -> None:
        """Start a transfer. If dry_run is True, only print what would be executed."""
        logger.debug(f"=== start_transfer: Starting ===")
        logger.debug(f"Repos: {repos}, dry_run: {dry_run}, cli_home_dir: {cli_home_dir}")
        
        # Set thread count before starting transfer (threads are not a command option)
        logger.debug(f"Adjusting threads to {self.config.transfer.threads} (cli_home_dir={cli_home_dir})...")
        self._adjust_threads(self.config.transfer.threads, dry_run=dry_run, cli_home_dir=cli_home_dir)
        logger.debug("Thread adjustment completed")
        
        logger.debug("Building transfer arguments...")
        logger.debug(f"Config ignore_state value: {self.config.transfer.ignore_state} (type: {type(self.config.transfer.ignore_state)})")
        args = self._build_transfer_args(repos)
        logger.debug(f"Transfer args: {args}")
        # Verify ignore-state argument
        ignore_state_arg = next((arg for arg in args if arg.startswith("--ignore-state=")), None)
        if ignore_state_arg:
            logger.debug(f"ignore-state argument: {ignore_state_arg}")
        
        if dry_run:
            env = os.environ.copy()
            env["JFROG_CLI_LOG_LEVEL"] = self.config.transfer.cli_log_level
            if cli_home_dir:
                env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)
            print("Would execute:")
            print(f"  Command: {' '.join([self.jf_cli.jfrog_cli_path] + args)}")
            print(f"  Environment: JFROG_CLI_LOG_LEVEL={self.config.transfer.cli_log_level}")
            if cli_home_dir:
                print(f"  Environment: JFROG_CLI_HOME_DIR={cli_home_dir}")
            print(f"  Repositories: {', '.join(repos)}")
            logger.debug("=== start_transfer: Dry run completed ===")
            return
        
        env = os.environ.copy()
        env["JFROG_CLI_LOG_LEVEL"] = self.config.transfer.cli_log_level
        if cli_home_dir:
            env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)
        
        logger.debug(f"Executing JFrog CLI command: {self.jf_cli.jfrog_cli_path} {' '.join(args)}")
        logger.debug(f"Environment: JFROG_CLI_LOG_LEVEL={env.get('JFROG_CLI_LOG_LEVEL')}, JFROG_CLI_HOME_DIR={env.get('JFROG_CLI_HOME_DIR')}")
        logger.debug(f"Working directory: {cli_home_dir}")
        
        result = self.jf_cli.run(args, env=env, cwd=str(cli_home_dir) if cli_home_dir else None)
        logger.debug(f"JFrog CLI command completed. Return code: {result.returncode}")
        logger.debug(f"stdout length: {len(result.stdout)} chars, stderr length: {len(result.stderr)} chars")
        
        if result.returncode != 0:
            logger.error(f"Transfer failed with return code {result.returncode}")
            logger.error(f"stderr: {result.stderr}")
            raise RuntimeError(f"transfer-files failed: {result.stderr}")
        
        logger.debug("=== start_transfer: Completed successfully ===")

    def start_transfer_per_repo(
        self,
        repo: str,
        run_dir: Path,
        dry_run: bool = False,
    ) -> Path:
        """Start a transfer for a single repo. Returns log file path."""
        cli_home_dir = self._get_cli_home_dir(repo, run_dir)
        log_file = run_dir / "logs" / f"{repo}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        self.start_transfer([repo], dry_run=dry_run, cli_home_dir=cli_home_dir)
        return log_file

    def status(self, cli_home_dir: Optional[Path] = None) -> str:
        """Check transfer status for a single CLI home.

        When cli_home_dir is provided, sets JFROG_CLI_HOME_DIR so the status
        check targets the correct (possibly isolated) CLI home.
        """
        logger.debug(f"Checking transfer status (cli_home_dir={cli_home_dir})...")
        args = [
            "rt",
            "transfer-files",
            "--status",
            self.config.jfrog.source_server_id,
            self.config.jfrog.target_server_id,
        ]
        env: dict | None = None
        if cli_home_dir:
            env = os.environ.copy()
            env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)

        logger.debug(f"Status command: {' '.join([self.jf_cli.jfrog_cli_path] + args)}")
        result = self.jf_cli.run(args, env=env)
        logger.debug(f"Status check return code: {result.returncode}")
        if result.returncode != 0:
            logger.warning(f"Status check failed: {result.stderr}")
            return result.stderr or "Status failed"
        status_text = result.stdout
        logger.debug(f"Status check successful (response length: {len(status_text)} chars)")
        return status_text

    def status_all(self) -> dict:
        """Check transfer status across all relevant CLI homes.

        Returns a dict mapping CLI home name to status string.
        For 'default' strategy returns {'default': <status>}.
        For 'per_repo_isolated' returns {<repo>: <status>, ...}.
        """
        results: dict = {}
        if self._is_per_repo_isolated():
            cli_homes = self._get_all_cli_homes()
            if not cli_homes:
                logger.warning("No cli_homes directories found")
            for repo_dir in cli_homes:
                results[repo_dir.name] = self.status(cli_home_dir=repo_dir)
        else:
            results["default"] = self.status()
        return results
    
    def _is_transfer_complete(self, status: str) -> bool:
        """Check if transfer is complete based on status output.
        
        The transfer is complete if:
        - Status contains "no running transfer" (case-insensitive)
        - Status contains "completed" or "finished" (case-insensitive)
        - Status is empty or indicates no active transfer
        """
        if not status:
            logger.debug("Status is empty, assuming transfer complete")
            return True
        
        status_lower = status.lower()
        
        # Check for explicit completion indicators
        # Note: JFrog CLI returns "🔴 Status: Not running" when no transfer is active
        completion_indicators = [
            "status: not running",
            "not running",
            "no running transfer",
            "no transfer in progress",
            "transfer completed",
            "transfer finished",
            "no active transfer",
        ]
        
        for indicator in completion_indicators:
            if indicator in status_lower:
                logger.debug(f"Found completion indicator: '{indicator}'")
                return True
        
        # Check for active transfer indicators
        active_indicators = [
            "transfer in progress",
            "running transfer",
            "transferring",
            "status: running",
            "in progress",
            "processing",
        ]
        
        for indicator in active_indicators:
            if indicator in status_lower:
                logger.debug(f"Found active transfer indicator: '{indicator}'")
                return False
        
        # If we can't determine status clearly, check if status is very short or empty-like
        # This might indicate the transfer is complete but status format is unexpected
        if len(status.strip()) < 50:
            logger.debug(f"Status is very short ({len(status)} chars) and no active indicators found, assuming complete")
            return True
        
        # If we can't determine, log warning but be more lenient - assume complete if no clear active indicators
        logger.warning(f"Could not definitively determine transfer status from: {status[:200]}")
        logger.warning("No active transfer indicators found, assuming transfer may be complete")
        return True  # Changed to True - if no active indicators, assume complete

    def stop(self, cli_home_dir: Optional[Path] = None) -> str:
        """Stop a running transfer in a single CLI home."""
        env: dict | None = None
        if cli_home_dir:
            env = os.environ.copy()
            env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)
        result = self.jf_cli.run(["rt", "transfer-files", "--stop"], env=env)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "Failed to stop transfer-files")
        return result.stdout

    def stop_all(self) -> dict:
        """Stop running transfers across all relevant CLI homes.

        Returns a dict mapping CLI home name to result string.
        """
        results: dict = {}
        if self._is_per_repo_isolated():
            cli_homes = self._get_all_cli_homes()
            if not cli_homes:
                logger.warning("No cli_homes directories found")
            for repo_dir in cli_homes:
                try:
                    output = self.stop(cli_home_dir=repo_dir)
                    results[repo_dir.name] = output or "stopped"
                except Exception as e:
                    results[repo_dir.name] = f"error: {e}"
        else:
            try:
                output = self.stop()
                results["default"] = output or "stopped"
            except Exception as e:
                results["default"] = f"error: {e}"
        return results

    def _run_per_repo_mode(
        self,
        repos: List[str],
        run_dir: Path,
        end_time: Optional[float],
        dry_run: bool,
    ) -> TransferResult:
        """Run transfers in per-repo mode with batching."""
        logger.debug("=== _run_per_repo_mode: Starting ===")
        logger.debug(f"Repos: {len(repos)}, run_dir: {run_dir}, end_time: {end_time}, dry_run: {dry_run}")
        
        if dry_run:
            logger.info(f"Would run {len(repos)} repos in per-repo mode with batch_size={self.config.transfer.batch_size}")
            return TransferResult(
                status="dry_run",
                started_at=time.time(),
                ended_at=time.time(),
                repos=repos,
                run_dir=run_dir,
                message="Dry run - per-repo mode",
            )
        
        started_at = time.time()
        log_files = {}
        completed_repos = []
        failed_repos = []
        restart_counts = {repo: 0 for repo in repos}
        max_restarts = 3
        
        # Split repos into batches
        batch_size = self.config.transfer.batch_size
        batches = [repos[i:i + batch_size] for i in range(0, len(repos), batch_size)]
        
        logger.info(f"Running {len(repos)} repos in {len(batches)} batches (batch_size={batch_size})")
        logger.debug(f"Batch breakdown: {[len(b) for b in batches]}")
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"Processing batch {batch_idx}/{len(batches)}: {batch}")
            logger.debug(f"=== Starting batch {batch_idx}/{len(batches)} ===")
            
            # Start transfers for this batch
            logger.debug(f"Starting transfers for {len(batch)} repos in batch {batch_idx}...")
            for repo in batch:
                try:
                    logger.debug(f"Starting transfer for repo: {repo}")
                    log_file = self.start_transfer_per_repo(repo, run_dir, dry_run=False)
                    log_files[repo] = log_file
                    logger.debug(f"Transfer started for {repo}, log file: {log_file}")
                except Exception as e:
                    logger.error(f"Failed to start transfer for {repo}: {e}")
                    failed_repos.append(repo)
            
            # Monitor batch
            monitor_iteration = 0
            while batch:
                monitor_iteration += 1
                current_time = time.time()
                logger.debug(f"Batch {batch_idx} monitoring iteration {monitor_iteration} (elapsed: {current_time - started_at:.1f}s)")
                
                if end_time and current_time >= end_time:
                    logger.info("End time reached, stopping transfers")
                    try:
                        self.stop_all()
                    except Exception:
                        pass
                    break
                
                remaining = []
                for repo in batch:
                    if repo in failed_repos:
                        logger.debug(f"Skipping {repo} (already failed)")
                        continue
                    
                    log_file = log_files.get(repo)
                    if not log_file or not log_file.exists():
                        logger.debug(f"{repo}: Log file not found, keeping in batch")
                        remaining.append(repo)
                        continue
                    
                    # Check if stuck
                    if self._check_stuck(log_file):
                        logger.debug(f"{repo}: Appears stuck (log file mtime: {log_file.stat().st_mtime})")
                        if restart_counts[repo] < max_restarts:
                            logger.warning(f"Transfer for {repo} appears stuck, restarting (attempt {restart_counts[repo] + 1})")
                            restart_counts[repo] += 1
                            try:
                                log_file = self.start_transfer_per_repo(repo, run_dir, dry_run=False)
                                log_files[repo] = log_file
                                remaining.append(repo)
                            except Exception as e:
                                logger.error(f"Restart failed for {repo}: {e}")
                                failed_repos.append(repo)
                        else:
                            logger.error(f"Transfer for {repo} stuck and max restarts reached")
                            failed_repos.append(repo)
                        continue
                    
                    # Check if completed — query the repo's own CLI home for status
                    logger.debug(f"Checking status for {repo}...")
                    cli_home = self._get_cli_home_dir(repo, run_dir)
                    status = self.status(cli_home_dir=cli_home)
                    if self._is_transfer_complete(status):
                        # Transfer finished, check if this repo's transfer completed
                        if repo not in completed_repos:
                            completed_repos.append(repo)
                            logger.info(f"Transfer completed for {repo}")
                            logger.debug(f"{repo} marked as completed")
                    else:
                        logger.debug(f"{repo} still running")
                        remaining.append(repo)
                
                batch = remaining
                if batch:
                    logger.debug(f"Batch {batch_idx}: {len(batch)} repos still running, sleeping for {self.config.transfer.poll_interval_seconds}s...")
                    time.sleep(self.config.transfer.poll_interval_seconds)
                else:
                    logger.debug(f"Batch {batch_idx}: All repos completed or failed")
            
            # Wait for batch to complete before starting next
            if batch_idx < len(batches):
                logger.info("Waiting for batch to complete before starting next batch...")
                wait_iteration = 0
                while any(r not in completed_repos and r not in failed_repos for r in batch):
                    wait_iteration += 1
                    logger.debug(f"Waiting for batch {batch_idx} completion (iteration {wait_iteration})...")
                    time.sleep(self.config.transfer.poll_interval_seconds)
                logger.debug(f"Batch {batch_idx} fully completed")
        
        ended_at = time.time()
        status_label = "completed" if not failed_repos else "partial"
        message = f"Completed: {len(completed_repos)}, Failed: {len(failed_repos)}"
        
        logger.debug(f"=== _run_per_repo_mode: Completed ===")
        logger.debug(f"Total time: {ended_at - started_at:.1f}s, Status: {status_label}, {message}")
        
        return TransferResult(
            status=status_label,
            started_at=started_at,
            ended_at=ended_at,
            repos=repos,
            run_dir=run_dir,
            message=message,
        )

    def run_and_monitor(
        self, 
        run_dir: Path, 
        end_time: Optional[float] = None,
        dry_run: bool = False,
    ) -> TransferResult:
        logger.debug("=== run_and_monitor: Starting ===")
        logger.debug(f"Run directory: {run_dir}, end_time: {end_time}, dry_run: {dry_run}")
        
        logger.debug("Loading repositories...")
        repos = load_repos(
            self.config.transfer.include_repos_file,
            self.config.transfer.include_repos_inline,
        )
        logger.debug(f"Loaded {len(repos)} repositories: {repos[:5]}{'...' if len(repos) > 5 else ''}")
        
        # Choose mode
        if self.config.transfer.mode == "per_repo":
            logger.debug(f"Using per_repo mode")
            return self._run_per_repo_mode(repos, run_dir, end_time, dry_run)
        
        # Single command mode (existing implementation)
        logger.debug(f"Using single_command mode")
        if dry_run:
            print(f"Would run transfer in directory: {run_dir}")
            print(f"Would monitor with poll interval: {self.config.transfer.poll_interval_seconds}s")
            if end_time:
                print(f"Would stop at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}")
            self.start_transfer(repos, dry_run=True)
            return TransferResult(
                status="dry_run",
                started_at=time.time(),
                ended_at=time.time(),
                repos=repos,
                run_dir=run_dir,
                message="Dry run - no actual transfer executed",
            )
        
        started_at = time.time()
        logger.debug(f"Starting transfer at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started_at))}")
        self.start_transfer(repos, dry_run=False)
        logger.debug("Transfer command completed, checking final status...")
        
        # The jf rt transfer-files command blocks until transfer completes.
        # Check status to confirm completion and get final status.
        final_status = self.status()
        logger.debug(f"Status after transfer command: {final_status[:200]}{'...' if len(final_status) > 200 else ''}")
        
        # Verify the transfer actually completed
        if self._is_transfer_complete(final_status):
            logger.info("Transfer completed successfully")
            ended_at = time.time()
            result = TransferResult(
                status="completed",
                started_at=started_at,
                ended_at=ended_at,
                repos=repos,
                run_dir=run_dir,
                message="Transfer completed",
            )
            self._write_summary(result)
            logger.debug("=== run_and_monitor: Completed ===")
            return result
        else:
            # Transfer command returned but status shows it's still running - enter monitoring loop
            logger.warning("Transfer command returned but status indicates transfer may still be running, entering monitoring loop")
            logger.debug("Entering monitoring loop...")
        poll = self.config.transfer.poll_interval_seconds
        status_label = "completed"
        message = None
        iteration = 0
        consecutive_complete_checks = 0
        required_complete_checks = 2  # Require 2 consecutive "complete" status checks to avoid false positives
        
        while True:
            iteration += 1
            current_time = time.time()
            elapsed = current_time - started_at
            logger.debug(f"Monitoring loop iteration {iteration} (elapsed: {elapsed:.1f}s)")
            
            if end_time and current_time >= end_time:
                logger.debug(f"End time reached ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(end_time))}), stopping transfer...")
                self.stop()
                status_label = "stopped_by_schedule"
                message = "Transfer stopped due to end_time"
                break
            
            logger.debug("Checking transfer status...")
            try:
                status = self.status()
                logger.debug(f"Status check returned (length: {len(status)} chars): {status[:200]}{'...' if len(status) > 200 else ''}")
                
                if self._is_transfer_complete(status):
                    consecutive_complete_checks += 1
                    logger.debug(f"Transfer complete detected (consecutive checks: {consecutive_complete_checks}/{required_complete_checks})")
                    
                    if consecutive_complete_checks >= required_complete_checks:
                        logger.info(f"Transfer completed detected after {consecutive_complete_checks} consecutive status checks, exiting monitoring loop")
                        break
                    else:
                        logger.debug(f"Waiting for {required_complete_checks - consecutive_complete_checks} more complete status check(s) to confirm...")
                else:
                    # Reset counter if status shows transfer is still running
                    if consecutive_complete_checks > 0:
                        logger.debug(f"Transfer status changed back to active, resetting completion counter")
                        consecutive_complete_checks = 0
            except Exception as e:
                logger.warning(f"Error checking status: {e}, continuing monitoring...")
                consecutive_complete_checks = 0
            
            logger.debug(f"Transfer still running, sleeping for {poll} seconds...")
            time.sleep(poll)

        ended_at = time.time()
        logger.debug(f"Monitoring loop exited after {iteration} iterations. Total time: {ended_at - started_at:.1f}s")
        result = TransferResult(
            status=status_label,
            started_at=started_at,
            ended_at=ended_at,
            repos=repos,
            run_dir=run_dir,
            message=message,
        )
        logger.debug("Writing summary...")
        self._write_summary(result)
        logger.debug("=== run_and_monitor: Completed ===")
        return result

    def _write_summary(self, result: TransferResult) -> None:
        summary = {
            "status": result.status,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "repos": result.repos,
            "message": result.message,
        }
        (result.run_dir / "summary.json").write_text(json.dumps(summary, indent=2))

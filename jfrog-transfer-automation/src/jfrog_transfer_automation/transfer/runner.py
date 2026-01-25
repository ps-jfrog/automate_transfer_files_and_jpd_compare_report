from __future__ import annotations

import json
import logging
import os
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

    def _build_transfer_args(self, repos: List[str]) -> List[str]:
        """Build the transfer-files command arguments."""
        return [
            "rt",
            "transfer-files",
            self.config.jfrog.source_server_id,
            self.config.jfrog.target_server_id,
            "--include-repos",
            self._include_repos_arg(repos),
            f"--filestore={str(self.config.transfer.filestore).lower()}",
            f"--ignore-state={str(self.config.transfer.ignore_state).lower()}",
            f"--threads={self.config.transfer.threads}",
        ]

    def _get_cli_home_dir(self, repo: str, run_dir: Path) -> Optional[Path]:
        """Get isolated CLI home directory for a repo if strategy is per_repo_isolated."""
        if self.config.transfer.jfrog_cli_home_strategy == "per_repo_isolated":
            repo_home = run_dir / "cli_homes" / repo
            repo_home.mkdir(parents=True, exist_ok=True)
            return repo_home
        return None

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
        args = self._build_transfer_args(repos)
        
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
            return
        
        env = os.environ.copy()
        env["JFROG_CLI_LOG_LEVEL"] = self.config.transfer.cli_log_level
        if cli_home_dir:
            env["JFROG_CLI_HOME_DIR"] = str(cli_home_dir)
        
        result = self.jf_cli.run(args, env=env, cwd=str(cli_home_dir) if cli_home_dir else None)
        if result.returncode != 0:
            raise RuntimeError(f"transfer-files failed: {result.stderr}")

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

    def status(self) -> str:
        result = self.jf_cli.run(["rt", "transfer-files", "--status"])
        if result.returncode != 0:
            return result.stderr or "Status failed"
        return result.stdout

    def stop(self) -> str:
        result = self.jf_cli.run(["rt", "transfer-files", "--stop"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "Failed to stop transfer-files")
        return result.stdout

    def resume(self, repos: List[str], dry_run: bool = False) -> None:
        """Resume a stopped transfer. This is essentially the same as start_transfer."""
        if dry_run:
            print("Would resume transfer with:")
            print(f"  Repositories: {', '.join(repos)}")
            return
        self.start_transfer(repos, dry_run=False)

    def _run_per_repo_mode(
        self,
        repos: List[str],
        run_dir: Path,
        end_time: Optional[float],
        dry_run: bool,
    ) -> TransferResult:
        """Run transfers in per-repo mode with batching."""
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
        
        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"Processing batch {batch_idx}/{len(batches)}: {batch}")
            
            # Start transfers for this batch
            for repo in batch:
                try:
                    log_file = self.start_transfer_per_repo(repo, run_dir, dry_run=False)
                    log_files[repo] = log_file
                except Exception as e:
                    logger.error(f"Failed to start transfer for {repo}: {e}")
                    failed_repos.append(repo)
            
            # Monitor batch
            while batch:
                if end_time and time.time() >= end_time:
                    logger.info("End time reached, stopping transfers")
                    try:
                        self.stop()
                    except Exception:
                        pass
                    break
                
                remaining = []
                for repo in batch:
                    if repo in failed_repos:
                        continue
                    
                    log_file = log_files.get(repo)
                    if not log_file or not log_file.exists():
                        remaining.append(repo)
                        continue
                    
                    # Check if stuck
                    if self._check_stuck(log_file):
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
                    
                    # Check if completed - in per-repo mode, we check if transfer is still running
                    # If no transfer is running and log file exists, assume completed
                    status = self.status()
                    if "no running transfer" in status.lower():
                        # Transfer finished, check if this repo's transfer completed
                        if repo not in completed_repos:
                            completed_repos.append(repo)
                            logger.info(f"Transfer completed for {repo}")
                    else:
                        remaining.append(repo)
                
                batch = remaining
                if batch:
                    time.sleep(self.config.transfer.poll_interval_seconds)
            
            # Wait for batch to complete before starting next
            if batch_idx < len(batches):
                logger.info("Waiting for batch to complete before starting next batch...")
                while any(r not in completed_repos and r not in failed_repos for r in batch):
                    time.sleep(self.config.transfer.poll_interval_seconds)
        
        ended_at = time.time()
        status_label = "completed" if not failed_repos else "partial"
        message = f"Completed: {len(completed_repos)}, Failed: {len(failed_repos)}"
        
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
        repos = load_repos(
            self.config.transfer.include_repos_file,
            self.config.transfer.include_repos_inline,
        )
        
        # Choose mode
        if self.config.transfer.mode == "per_repo":
            return self._run_per_repo_mode(repos, run_dir, end_time, dry_run)
        
        # Single command mode (existing implementation)
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
        self.start_transfer(repos, dry_run=False)

        poll = self.config.transfer.poll_interval_seconds
        status_label = "completed"
        message = None
        while True:
            if end_time and time.time() >= end_time:
                self.stop()
                status_label = "stopped_by_schedule"
                message = "Transfer stopped due to end_time"
                break
            status = self.status()
            if "no running transfer" in status.lower():
                break
            time.sleep(poll)

        ended_at = time.time()
        result = TransferResult(
            status=status_label,
            started_at=started_at,
            ended_at=ended_at,
            repos=repos,
            run_dir=run_dir,
            message=message,
        )
        self._write_summary(result)
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

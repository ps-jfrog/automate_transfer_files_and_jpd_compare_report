from __future__ import annotations

import logging
import platform
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CLIResult:
    returncode: int
    stdout: str
    stderr: str


class JFrogCLI:
    def __init__(self, jfrog_cli_path: str = "jf") -> None:
        self.jfrog_cli_path = jfrog_cli_path

    def _prepare_command(
        self,
        args: List[str],
        env: Optional[dict],
        cwd: Optional[str],
    ) -> tuple[list[str], bool]:
        """Build the full command list, determine shell mode, and log details."""
        command = [self.jfrog_cli_path] + args
        use_shell = platform.system().lower() == "windows"
        logger.debug(f"Command: {' '.join(command)}")
        logger.debug(f"Working directory: {cwd}")
        logger.debug(f"Environment keys: {list(env.keys()) if env else 'None'}")
        return command, use_shell

    def run(
        self,
        args: List[str],
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        check: bool = False,
    ) -> CLIResult:
        """Execute a JFrog CLI command synchronously (blocks until complete)."""
        command, use_shell = self._prepare_command(args, env, cwd)
        start_time = time.time()
        try:
            completed = subprocess.run(
                command,
                env=env,
                cwd=cwd,
                check=check,
                text=True,
                capture_output=True,
                shell=use_shell,
            )
            elapsed = time.time() - start_time
            logger.debug(f"Command completed in {elapsed:.2f}s. Return code: {completed.returncode}")
            logger.debug(f"stdout length: {len(completed.stdout)} chars, stderr length: {len(completed.stderr)} chars")
            result = CLIResult(
                returncode=completed.returncode,
                stdout=completed.stdout.strip(),
                stderr=completed.stderr.strip(),
            )
            logger.debug(f"=== JFrogCLI.run: Completed ===")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Command failed after {elapsed:.2f}s with exception: {e}")
            raise

    def run_background(
        self,
        args: List[str],
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        stdout=None,
        stderr=None,
    ) -> subprocess.Popen:
        """Launch a JFrog CLI command as a background process (non-blocking).

        Returns the Popen handle so the caller can monitor via poll()/wait().
        stdout/stderr default to DEVNULL when not provided.
        """
        command, use_shell = self._prepare_command(args, env, cwd)
        proc = subprocess.Popen(
            command,
            env=env,
            cwd=cwd,
            stdout=stdout if stdout is not None else subprocess.DEVNULL,
            stderr=stderr if stderr is not None else subprocess.DEVNULL,
            text=True,
            shell=use_shell,
        )
        logger.debug(f"Background process launched: PID={proc.pid}")
        return proc

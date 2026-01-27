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

    def run(
        self,
        args: List[str],
        env: Optional[dict] = None,
        cwd: Optional[str] = None,
        check: bool = False,
    ) -> CLIResult:
        command = [self.jfrog_cli_path] + args
        use_shell = platform.system().lower() == "windows"
        
        logger.debug(f"=== JFrogCLI.run: Executing command ===")
        logger.debug(f"Command: {' '.join(command)}")
        logger.debug(f"Working directory: {cwd}")
        logger.debug(f"Environment keys: {list(env.keys()) if env else 'None'}")
        
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

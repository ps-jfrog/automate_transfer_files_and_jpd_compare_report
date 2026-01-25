from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import List, Optional


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
        completed = subprocess.run(
            command,
            env=env,
            cwd=cwd,
            check=check,
            text=True,
            capture_output=True,
            shell=use_shell,
        )
        return CLIResult(
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
        )

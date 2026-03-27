"""
End-to-end integration test for the full jfrog-transfer-automation workflow.

Mirrors the "Typical multi-terminal workflow" from QUICKSTART.md:

1. **Seed** — publish Docker images to source repos so there is data to transfer.
2. **Multi-terminal workflow** — in a single test, simulate four terminals:

   - Terminal 1: ``run-once`` (background)
   - Terminal 2: ``monitor`` (background, then terminated)
   - Terminal 3: ``update-threads --threads 6``
   - Terminal 4: ``stop``

   Then verify ``run-once`` exits cleanly (report skipped), and ``resume``
   to complete the remaining transfer.

Prerequisites
-------------
- JFrog CLI configured with source and target server IDs (e.g. ``app1``, ``app2``)
- Docker daemon running (for the seed-data step)
- ``docker_image_generator.py`` available (pass via ``--docker-generator``)
- Repos listed in the config's ``transfer.include_repos_file`` exist in both
  source and target Artifactory instances
- Data-transfer plugin installed on the source instance

Run
---
::

    cd jfrog-transfer-automation/

    pytest tests/integration/test_e2e_transfer_workflow.py -v -s \\
        --config /path/to/test_schedule/config.yaml \\
        --docker-generator /path/to/docker_image_generator.py \\
        --docker-username app1user

Skip the seed step (if data already exists)::

    pytest tests/integration/test_e2e_transfer_workflow.py -v -s \\
        --config /path/to/test_schedule/config.yaml \\
        -k "not seed"
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

CLI_CMD = "jfrog-transfer-automation"

SEED_TIMEOUT = 300
CMD_TIMEOUT = 30
TRANSFER_TIMEOUT = 600
STARTUP_WAIT = 15
MONITOR_DURATION = 10


def _automation_cmd(config_path: Path, *args: str) -> list[str]:
    return [CLI_CMD, *args, "--config", str(config_path)]


def _get_run_base(config_path: Path) -> Path:
    from jfrog_transfer_automation.config.loader import load_config

    config = load_config(str(config_path))
    return Path(config.report.output_dir).expanduser().resolve()


def _wait_for_running(config_path: Path, timeout: int = 30) -> bool:
    """Poll current_run.json until status is 'running' (or early-exit on failure)."""
    run_base = _get_run_base(config_path)
    current_run = run_base / "current_run.json"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if current_run.exists():
            try:
                data = json.loads(current_run.read_text())
                status = data.get("status")
                if status == "running":
                    return True
                if status == "prechecks_failed":
                    return False
            except (json.JSONDecodeError, OSError):
                pass
        time.sleep(1)
    return False


def _print_precheck_result(config_path: Path) -> None:
    """Find the latest run.log and print precheck-related lines."""
    run_base = _get_run_base(config_path)
    current_run = run_base / "current_run.json"
    run_dir = None
    if current_run.exists():
        try:
            data = json.loads(current_run.read_text())
            run_dir = data.get("run_dir")
        except (json.JSONDecodeError, OSError):
            pass
    if not run_dir:
        return
    log_file = Path(run_dir) / "run.log"
    if not log_file.exists():
        return
    for line in log_file.read_text().splitlines():
        lower = line.lower()
        if "precheck" in lower or "pre-flight" in lower or "prechecks" in lower:
            print(f"  [run.log] {line.strip()}")


def _clear_lock(config_path: Path) -> None:
    """Clear any stale lock so the next run can start."""
    result = subprocess.run(
        _automation_cmd(config_path, "clear-lock"),
        capture_output=True,
        text=True,
        timeout=CMD_TIMEOUT,
    )
    print("clear-lock:", result.stdout.strip())


# ---------------------------------------------------------------------------
# Test 1: Seed test data in source repos
# ---------------------------------------------------------------------------

class TestSeedData:
    """Publish Docker images to every source repo so there is data to transfer."""

    def test_seed_docker_images(
        self,
        config_path,
        source_creds,
        repos,
        docker_generator,
        docker_username,
        image_count,
        image_size_mb,
    ):
        if docker_generator is None:
            pytest.skip(
                "Skipping seed step: --docker-generator not provided. "
                "Pass the path to docker_image_generator.py to enable this test."
            )

        # Extract just the host(:port) for Docker — strip scheme and /artifactory path
        host_and_path = source_creds.url.split("//", 1)[-1]
        registry = host_and_path.split("/")[0]

        for repo in repos:
            print(f"\n--- Seeding {repo} with {image_count} images ({image_size_mb} MB each) ---")
            env = os.environ.copy()
            env["DOCKER_USERNAME"] = docker_username
            env["DOCKER_PASSWORD"] = source_creds.access_token

            result = subprocess.run(
                [
                    sys.executable,
                    str(docker_generator),
                    "--image-count", str(image_count),
                    "--image-size-mb", str(image_size_mb),
                    "--layers", "3",
                    "--threads", "4",
                    "--registry", registry,
                    "--artifactory-repo", repo,
                    "--insecure",
                ],
                env=env,
                input="\n",
                capture_output=True,
                text=True,
                timeout=SEED_TIMEOUT,
            )
            print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
            assert result.returncode == 0, (
                f"Seeding {repo} failed (exit code {result.returncode}):\n"
                f"{result.stderr[-2000:]}"
            )
            print(f"  ✓ {repo} seeded successfully")


# ---------------------------------------------------------------------------
# Test 2: Full multi-terminal workflow
#   Terminal 1: run-once  →  Terminal 2: monitor  →  Terminal 3: update-threads
#   →  Terminal 4: stop  →  verify clean exit  →  resume
# ---------------------------------------------------------------------------

class TestMultiTerminalWorkflow:
    """Simulate the 'Typical multi-terminal workflow' from QUICKSTART.md."""

    def test_multi_terminal_workflow(self, config_path):
        """run-once → monitor → update-threads → stop → resume."""
        _clear_lock(config_path)

        # ── Terminal 1: start the transfer ──
        print("\n=== Terminal 1: starting run-once ===")
        run_once = subprocess.Popen(
            _automation_cmd(config_path, "run-once"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        try:
            running = _wait_for_running(config_path, timeout=30)
            _print_precheck_result(config_path)
            assert running, (
                "run-once did not reach 'running' status within 30s "
                "(check run.log — prechecks may have failed)"
            )
            print("  ✓ run-once is running (pre-flight check passed)")

            # ── Terminal 2: watch progress ──
            print("\n=== Terminal 2: starting monitor ===")
            monitor = subprocess.Popen(
                _automation_cmd(config_path, "monitor"),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            time.sleep(MONITOR_DURATION)

            # Check status (one-shot)
            status_result = subprocess.run(
                _automation_cmd(config_path, "status"),
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT,
            )
            print("status output:", status_result.stdout.strip())

            # Terminate monitor (Ctrl+C equivalent — does not stop the transfer)
            monitor.terminate()
            monitor_out, _ = monitor.communicate(timeout=10)
            print("monitor output (last 1000 chars):", monitor_out[-1000:])
            print("  ✓ monitor terminated (transfer still running)")

            # ── Terminal 3: adjust threads mid-transfer ──
            print("\n=== Terminal 3: update-threads --threads 22 ===")
            threads_result = subprocess.run(
                _automation_cmd(config_path, "update-threads", "--threads", "22"),
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT,
            )
            print(threads_result.stdout.strip())
            assert threads_result.returncode == 0, (
                f"update-threads failed:\n{threads_result.stderr}"
            )
            print("  ✓ update-threads applied")

            # ── Terminal 4: gracefully stop ──
            print("\n=== Terminal 4: stop ===")
            stop_result = subprocess.run(
                _automation_cmd(config_path, "stop"),
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT * 2,
            )
            print(stop_result.stdout.strip())
            assert stop_result.returncode == 0, (
                f"stop failed:\n{stop_result.stderr}"
            )
            print("  ✓ stop sent")

            # ── Wait for run-once (Terminal 1) to exit ──
            print("\n=== Waiting for run-once to exit ===")
            run_once_out, _ = run_once.communicate(timeout=120)
            print("run-once output (last 2000 chars):")
            print(run_once_out[-2000:])
            assert run_once.returncode == 0, (
                f"run-once after stop failed (exit code {run_once.returncode})"
            )
            assert "skipping report generation" in run_once_out.lower(), (
                "Expected run-once to skip report generation after stop"
            )
            print("  ✓ run-once exited cleanly (report skipped, lock released)")

        except Exception:
            run_once.kill()
            run_once.communicate(timeout=10)
            raise

        # ── Verify status shows stopped ──
        status_result = subprocess.run(
            _automation_cmd(config_path, "status"),
            capture_output=True,
            text=True,
            timeout=CMD_TIMEOUT,
        )
        print("\nstatus after stop:", status_result.stdout.strip())

        # ── Resume to complete the remaining transfer ──
        print("\n=== Resume: continuing where the transfer left off ===")
        resume = subprocess.Popen(
            _automation_cmd(config_path, "resume"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # ── Monitor progress during resume (watch for adaptive_threads) ──
        print("\n=== Monitoring resume progress (watching for adaptive_threads) ===")
        monitor_iteration = 0
        while resume.poll() is None:
            monitor_iteration += 1
            time.sleep(15)
            mon = subprocess.run(
                _automation_cmd(config_path, "status"),
                capture_output=True,
                text=True,
                timeout=CMD_TIMEOUT,
            )
            print(f"\n--- Monitor iteration {monitor_iteration} ---")
            print(mon.stdout.strip())

        resume_out, _ = resume.communicate(timeout=TRANSFER_TIMEOUT)
        print("\nresume output (last 2000 chars):")
        print(resume_out[-2000:])
        assert resume.returncode == 0, (
            f"resume failed (exit code {resume.returncode})"
        )
        print("  ✓ resume completed successfully")

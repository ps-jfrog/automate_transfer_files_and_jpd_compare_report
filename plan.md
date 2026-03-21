# JFrog Transfer Sync Automator - Implementation Plan

## Goal
Build a Python application (Windows-friendly) that **automates daily delta syncs** using `jf rt transfer-files` (after the initial multi‑TB sync), and **generates + delivers a high-level comparison report** (per `prepare_and_generate_comparison_report/README.md`) on a daily schedule.

Key requirements:
- Configurable daily schedule: **start time** required; **end time** optional.
- If a run is still active when the next scheduled start occurs, **do not start a new run** (queue/skip until prior completes).
- Use **JFrog CLI configuration** (server IDs) to discover **JPD URL + access token** (like `jfrog-role-manager`'s `src/auth.py`) and to run CLI commands / call REST APIs.
- Best practices: packaging, structured logging, clear error handling, testability, extensible architecture.

---

## Inputs from the provided helper scripts (what we will reuse)
### Transfer automation helper
- `jfrog_multi_repo_artifacts_sync_via_transfer-files.py`
  - Runs `jf rt transfer-files` per-repo, supports per-repo CLI home dir (`JFROG_CLI_HOME_DIR`), writes logs, restarts if "stuck" (log not updated), and supports batching via multiprocessing.
  - **Gaps vs. target use-case**: not scheduled, not Windows-oriented, not integrated with report generation, no single-run lock across schedules.

### Comparison report helper
- `prepare_and_generate_comparison_report.sh` + README
  - Calls:
    - `POST /api/storageinfo/calculate`
    - `GET /api/repositories?type=local` (optionally federated)
    - `GET /api/storageinfo`
    - Runs `compare_repo_list_details_in_source_vs_target_rt_after_migration.py` to produce a human-readable report.
  - **Gaps**: bash + `jq` dependency, not Windows-friendly; needs to be converted to Python and integrated.

### Existing scaffold example
- `jfrog-role-manager/`
  - Demonstrates packaging, `src/` layout, CLI entry point, structured logging, and—critically—how to extract URL/token via `jf c export <server-id>` (base64 JSON). Reuse this approach.

---

## Proposed application: `jfrog-transfer-automation` (working name)

### High-level workflow per scheduled run
1. Acquire a **global run lock** (prevents overlap).
2. Validate prerequisites: `jf` in PATH, required server IDs exist, repo list available, output dirs writable.
3. Start/continue transfer:
   - For each repo (or repo group), run `jf rt transfer-files <source> <target> --include-repos "..."`
   - Option A (simple): run once with semicolon-separated repos (sequential in CLI).
   - Option B (advanced / borrowed from helper): per-repo isolated `JFROG_CLI_HOME_DIR` + parallel batches.
4. Monitor:
   - Periodically call `jf rt transfer-files --status` (and optionally parse output).
   - If `end_time` configured and reached, call `jf rt transfer-files --stop` and mark run as "stopped by schedule".
5. Generate report:
   - Call Artifactory REST APIs (or `jf rt curl`) to fetch `storageinfo` and repo list.
   - Produce the "high-level comparison report" text file.
6. Deliver report:
   - Default: write to disk (per-run folder) + print path.
   - Optional: send email (SMTP) / post to webhook (Teams/Slack) / upload to share (future).
7. Release lock; write run summary JSON (start/end, repos attempted, status, paths, errors).

---

## Configuration design (YAML)
Create `config.yaml`  with explicit sections:

```yaml
schedule:
  timezone: "America/Los_Angeles"        # default if omitted
  start_time: "01:00"                    # required (24h)
  end_time: "05:00"                      # optional
  run_on_startup: false                  # optional
  catch_up_if_missed: false              # optional (usually false)

jfrog:
  jfrog_cli_path: "jf"                   # or absolute path
  source_server_id: "source-server"
  target_server_id: "target-server"

transfer:
  include_repos_file: "repos.txt"        # one repo per line (supports comments)
  include_repos_inline: null             # optional alternative
  mode: "single_command"                 # single_command | per_repo
  threads: 8
  filestore: true
  ignore_state: false
  batch_size: 4                          # only for per_repo
  stuck_timeout_seconds: 600             # only for per_repo
  poll_interval_seconds: 60
  jfrog_cli_home_strategy: "default"     # default | per_repo_isolated

report:
  enabled: true
  repo_type: "local"                     # local | federated
  output_dir: "./runs"


notify:
  method: "none"                         # none | email | webhook
  email:
    smtp_host: ""
    smtp_port: 587
    smtp_user: ""
    smtp_password_env: "SMTP_PASSWORD"   # avoid storing secrets in file
    to: ["team@example.com"]
    from: "jfrog-automation@example.com"
  webhook:
    url: ""
    headers: {}
```

Also support environment-variable overrides for secrets (tokens, SMTP passwords).

---

## Project scaffolding (similar to `jfrog-role-manager`)
Recommended layout:

```
jfrog-transfer-automation/
  README.md
  QUICKSTART.md
  PACKAGING.md
  VERSIONING.md
  plan.md
  pyproject.toml                # prefer modern packaging (or setup.py if required)
  requirements.txt              # optional lock/constraints
  src/
    jfrog_transfer_automation/
      __init__.py
      cli/
        main.py                 # entry point (argparse/typer/click)
        commands/
          run_once.py
          scheduler.py
          status.py
          stop.py
          report.py
          validate.py
      config/
        model.py                # pydantic models (optional)
        loader.py               # YAML parsing + validation
      logging/
        setup.py                # json/text logging, rotation
      jfrog/
        cli.py                  # wrapper around `jf` subprocess
        auth.py                 # reuse `jf c export` logic
        artifactory_api.py      # requests client using url/token
      transfer/
        runner.py               # run transfer-files, monitor, stop
        repo_list.py            # parse repo list files
        locks.py                # file lock + run state
      report/
        generator.py            # python implementation of prepare_and_generate_comparison_report
        compare_adapter.py      # invoke/port compare_repo_list_details... script
      notify/
        emailer.py
        webhook.py
      util/
        time.py                 # schedule/time-window helpers
        proc.py                 # cross-platform process helpers
  tests/
    test_config.py
    test_schedule.py
    test_locking.py
    test_repo_list.py
    test_report_generator.py
  scripts/
    install.ps1
    install.sh
```

---

## Task breakdown

## Phase 0 — Discovery and alignment
1. **Review helper scripts** and document reusable logic:
   - Transfer execution patterns (single command vs per-repo).
   - "Stuck" detection + restart behavior.
   - Report generation inputs/outputs and required API calls.
2. Decide "MVP mode" (recommended):
   - **MVP**: single `transfer-files` invocation with `--include-repos "repo1;repo2;..."` + status polling.
   - **Phase 2**: optional per-repo isolated `JFROG_CLI_HOME_DIR` + batching (from helper).

Deliverable: short design note in `README.md` (MVP vs advanced modes).

---

## Phase 1 — Repository scaffolding & packaging
1. Initialize project skeleton (folders, modules, tests).
2. Add packaging:
   - `pyproject.toml` with console script entry point, versioning.
3. Add dependencies:
   - `pyyaml` (config)
   - `requests` (REST calls)
   - `portalocker` (cross-platform file locks) or `fasteners`
   - `pydantic` (optional config validation)
   - `tenacity` (optional retries)
4. Add logging:
   - Rotating file handler + console
   - Per-run log directory under `runs/<run_id>/logs/`
   - Include run_id in every log line.

Deliverables: installable package + `jfrog-transfer-automation` CLI command.

---

## Phase 2 — JFrog integration layer
1. Implement `jfrog.auth.extract_cli_config(server_id)`:
   - Copy approach from `jfrog-role-manager/src/auth.py`:
     - `jf c show <server-id>` validate exists
     - `jf c export <server-id>` (base64 JSON)
     - parse `url` + `accessToken`
   - Windows: `shell=True` handling (as role-manager does).
2. Implement `jfrog.cli.JFrogCLI` wrapper:
   - `run(args: list[str], env: dict, cwd: Path) -> CompletedProcess`
   - consistent stdout/stderr capture + logging
3. Implement `jfrog.artifactory_api.ArtifactoryClient`:
   - `POST /artifactory/api/storageinfo/calculate`
   - `GET /artifactory/api/storageinfo`
   - `GET /artifactory/api/repositories?type=local|federated`
   - Support `verify_ssl` config; timeouts; retries.

Deliverables: unit tests with mocked subprocess/HTTP.

---

## Phase 3 — Transfer runner (delta sync)
1. Implement repo selection:
   - parse repo file with comments/blank lines
   - allow `include_repos_inline` override
2. Implement `transfer.runner.TransferRun`:
   - Start transfer (single command or per-repo mode):
     - `jf rt transfer-files <src> <tgt> --include-repos "a;b;c" --filestore=... --ignore-state=...`
     - export `JFROG_CLI_LOG_LEVEL=DEBUG` (configurable)
   - Monitor status:
     - `jf rt transfer-files --status`
     - Detect "no running transfer" vs "active"
3. Implement scheduled stop:
   - If end_time is set, when the window ends:
     - call `jf rt transfer-files --stop`
     - mark run as "stopped_by_schedule"
4. Implement "stuck" detection & restart:
   - replicate helper's log-file mtime approach
   - enforce max restarts per repo / run
5. Implement per-repo mode:
   - Support `mode: "per_repo"` to run transfers per repository
   - Implement batching with `batch_size` for parallel execution
   - Support `jfrog_cli_home_strategy: "per_repo_isolated"` for isolated CLI home directories
6. Persist per_repo_isolated CLI homes across runs:
   - Store isolated CLI homes at `<output_dir>/cli_homes/<repo>/` instead of under the
     ephemeral per-run timestamped directory so that JFrog CLI transfer state is preserved
     across scheduled runs (enabling proper delta sync).
   - Each repo still gets its own JFROG_CLI_HOME_DIR for concurrency safety within a run.
7. Bootstrap isolated CLI homes with server configurations:
   - When `jfrog_cli_home_strategy: "per_repo_isolated"` is used, the isolated CLI home
     directories start empty and have no JFrog CLI server configurations, causing
     `Server ID '...' does not exist` errors.
   - On first use of an isolated CLI home, export the `jfrog.source_server_id` and
     `jfrog.target_server_id` configs from the default CLI home (`~/.jfrog`) using
     `jf c export <server_id>`, then import them into the isolated home using
     `jf c import <token>` with `JFROG_CLI_HOME_DIR` set to the isolated directory.
   - Skip the bootstrap if the server configs are already present (check via `jf c show`
     with `JFROG_CLI_HOME_DIR` set) so it only runs once per repo.
   - Add a `_bootstrap_cli_home(cli_home_dir)` method to `TransferRunner` and call it
     from `_get_cli_home_dir` (or `start_transfer`) before executing any transfer command.
8. Fix `_adjust_threads` to respect isolated CLI home directories:
   - `_adjust_threads` runs `jf rt transfer-settings` via raw `subprocess.run` without
     setting `JFROG_CLI_HOME_DIR`, so thread settings are applied to the default
     `~/.jfrog` home while the actual transfer runs in the isolated per-repo home.
   - Add an optional `cli_home_dir` parameter to `_adjust_threads` and set
     `JFROG_CLI_HOME_DIR` in the subprocess environment when provided.
   - Update `start_transfer` to forward its `cli_home_dir` argument to `_adjust_threads`.
9. Add `update-threads` CLI command for dynamic thread changes:
   - Add an `update_threads(thread_count)` method to `TransferRunner` that discovers all
     relevant CLI home directories (default or per-repo isolated) and calls
     `_adjust_threads` for each one.
   - Add `cmd_update_threads` in `cli/main.py` with an optional `--threads` flag to
     override the config value for a one-off change.
   - Safe to run while a transfer is in progress; changes take effect on the next
     transfer chunk.

10. Adapt `status`, `stop`, `resume`, and `monitor` commands for `per_repo_isolated`:
    - All four commands currently run `jf rt transfer-files --status` / `--stop` against
      the **default** CLI home (`~/.jfrog`), which has no knowledge of transfers running
      in isolated per-repo CLI homes.  They report "Not running" or fail to stop anything.
    - **`status`** (`cmd_status` + `runner.status()`): iterate over each
      `<output_dir>/cli_homes/<repo>/` and run `--status` with `JFROG_CLI_HOME_DIR` set.
      Aggregate per-repo results into a combined status display.
    - **`stop`** (`cmd_stop` + `runner.stop()`): send `--stop` to each isolated CLI home
      so running per-repo transfers actually receive the signal.
    - **`resume`** (`cmd_resume` + `runner.resume()`): currently calls
      `start_transfer(repos)` with no `cli_home_dir`, bypassing per-repo mode entirely.
      Should delegate to `run_and_monitor()` which already handles per-repo mode correctly.
    - **`monitor`** (`cmd_monitor`): polls `--status` against the default home in a loop.
      Same fix as `status` — query each isolated CLI home per iteration.
    - **`runner.status()` inside `_run_per_repo_mode`**: the internal monitoring loop
      calls `self.status()` against the default home; should accept an optional
      `cli_home_dir` and pass it when checking per-repo transfer status.
    - **`clear-lock`**: add a new CLI command that removes the `.lock` file and resets
      `current_run.json` when no process actually holds the lock.  Useful when a crashed
      run leaves a stale lock file (especially on NFS or platforms where advisory locks
      are not automatically cleaned up).  Should verify that no process currently holds
      the lock before removing, and warn if the lock is still held.
    - Commands that are already correct: `run-once` (delegates to `_run_per_repo_mode`),
      `validate` (checks default home for server configs — correct), `report` (REST API,
      no CLI home dependency), `scheduler`/`simulate-missed` (delegate to `run-once`),
      `update-threads` (already adapted).

Deliverables: `jfrog-transfer-automation run-once --config config.yaml`,
`jfrog-transfer-automation update-threads --config config.yaml [--threads N]`,
`jfrog-transfer-automation clear-lock --config config.yaml`.

---

## Phase 4 — Report generation (Windows-friendly)
1. Port `prepare_and_generate_comparison_report.sh` to Python:
   - Use `ArtifactoryClient` OR `jf rt curl` (config switch)
   - Write:
     - `source-storageinfo-<ts>.json`
     - `target-storageinfo-<ts>.json`
     - `all-local-repo-source-<ts>.txt` (sorted)
2. Integrate comparison logic:
   - Option A: vendor/port `compare_repo_list_details_in_source_vs_target_rt_after_migration.py` into `report/compare_adapter.py` as a callable module.
   - Option B: invoke it as a subprocess (simpler initially), passing args and capturing output.
3. Generate "high-level comparison report":
   - Save to `runs/<run_id>/reports/comparison-<ts>.txt`
   - Also produce a machine-readable summary JSON (counts, mismatches, totals).

Deliverables: `jfrog-transfer-automation report --config config.yaml`.

---

## Phase 5 — Scheduler (daily, non-overlapping runs)
1. Implement schedule parser:
   - `start_time` required; parse HH:MM (24h)
   - `end_time` optional; validate end after start (support crossing midnight if needed, document behavior)
2. Implement locking + run state:
   - A single **lock file** (e.g., `runs/.lock`) held for the duration of a run.
   - A `runs/current_run.json` with pid, start time, mode, status.
   - On startup, if lock is held:
     - print "run in progress" and do not start a second run.
3. Implement scheduler loop:
   - A long-running `scheduler` command that:
     - sleeps until next start
     - checks lock
     - launches run
   - Keep it dependency-light (no need for APScheduler), but APScheduler is acceptable if desired.
4. Implement `catch_up_if_missed` functionality:
   - Track last successful run timestamp
   - On scheduler startup, check if any scheduled windows were missed
   - If `catch_up_if_missed: true`, run missed transfers before waiting for next scheduled time
5. Add schedule simulation/testing feature:
   - Add `simulate-missed` command to manually trigger catch-up behavior
   - Allow setting a fake "last run" timestamp for testing
   - Document how to test missed schedule scenarios
6. Optimize catch-up to run a single transfer:
   - Delta sync via `jf rt transfer-files` covers the full backlog regardless of how many schedule
     windows were missed, so running one `cmd_run_once` is sufficient.
   - Both `cmd_simulate_missed` and `cmd_scheduler` catch-up blocks should detect missed windows
     but only execute a single transfer (instead of one per missed window).
   - Log all missed windows for visibility, then run one transfer covering them all.
7. Provide Windows guidance:
   - Use Windows Task Scheduler to run `jfrog-transfer-automation scheduler --config ...` at boot, or run `run-once` daily.
   - Document both patterns.

Deliverables:
- `jfrog-transfer-automation scheduler --config config.yaml`
- `jfrog-transfer-automation simulate-missed --config config.yaml --days-ago N`
- robust behavior under overlap scenarios.

---

## Phase 6 — Notifications (deliver the report)
1. Implement email sender (optional but common expectation for "send them report"):
   - Attach report or include summary in body; link to local path.
   - Support TLS and auth; secrets via env vars.
2. Implement webhook notifier (optional):
   - POST JSON payload + short text summary to Teams/Slack webhook.
3. Add "notification failures do not break the run" policy (log error, mark notify_failed).

Deliverables: `notify` module + config examples.

---

## Phase 7 — CLI UX, docs, and examples
1. CLI commands (suggested):
   - `validate` (checks jf, config, server IDs)
   - `run-once` (runs transfer + report + notify)
   - `status` (prints `jf rt transfer-files --status` and last run summary)
   - `stop` (calls `jf rt transfer-files --stop`)
   - `resume` (resume a stopped transfer)
   - `monitor` (continuously monitor transfer progress)
   - `report` (generate report only)
   - `scheduler` (daily loop)
   - `simulate-missed` (simulate missed schedule for testing)
   - `update-threads` (dynamically change transfer thread count, even mid-run)
   - `clear-lock` (remove stale lock file and reset run state after a crash)
2. Docs:
   - `QUICKSTART.md`: Windows instructions + sample `config.yaml`
   - `README.md`: overview, assumptions, security notes
   - `TROUBLESHOOTING.md`: common CLI/config/auth issues

Deliverables: polished docs for customer handoff.

---

## Phase 8 — Quality: tests, CI, and release
1. Unit tests for:
   - config parsing/validation
   - schedule calculations (next run time)
   - file locking / overlap prevention
   - repo list parsing
   - report generator (mock HTTP)
2. Integration test harness (optional):
   - "dry run" mode that prints commands without executing.
3. CI:
   - run tests on Windows + Linux
   - linting/formatting: ruff + black (optional)
4. Release packaging:
   - versioning + changelog
   - optionally produce a single-file executable via PyInstaller for easier Windows distribution.
5. Install scripts:
   - `scripts/install.ps1` for Windows
   - `scripts/install.sh` for Unix/Linux

Deliverables: reproducible builds and a distributable artifact.

---

## Implementation notes & decisions to document
- **Overlap behavior**: when the next start time arrives and a run is still active, the scheduler will **skip** that start and wait for the next day (or optionally "start immediately after completion" if enabled).
- **End time behavior**:
  - If set, the runner will attempt a graceful stop via `jf rt transfer-files --stop`.
  - It will still generate a report (useful to see partial progress), unless disabled.
- **Auth strategy**:
  - Prefer CLI config extraction (`jf c export`) to avoid putting tokens in config files.
  - Allow explicit override in config for air-gapped / restricted environments.
- **Extensibility**:
  - Keep "transfer", "report", "notify", and "scheduler" as independent services wired by a small orchestrator to support future expansion.

---

## Deliverables checklist
- [x] Python package scaffold (src/tests, packaging, logging)
- [x] Config spec + sample config
- [x] JFrog CLI config extraction (url/token)
- [x] Transfer runner (start/status/stop, non-overlapping)
- [x] Python report generator (no bash/jq)
- [x] Notification module (at least file output; optionally email/webhook)
- [x] Scheduler command (daily, optional end time)
- [x] Documentation + examples
- [x] Tests + CI (Windows coverage)
- [x] Per-repo transfer mode with batching
- [x] Stuck detection and restart logic
- [x] Per-repo isolated JFROG_CLI_HOME_DIR strategy
- [x] Persist per_repo_isolated CLI homes across runs for delta sync state preservation
- [x] Bootstrap isolated CLI homes with source/target server configs on first use
- [x] Fix `_adjust_threads` to respect isolated CLI home directories (JFROG_CLI_HOME_DIR)
- [x] `update-threads` CLI command for dynamic thread changes (even mid-run)
- [x] Adapt `status`, `stop`, `resume`, `monitor` commands for `per_repo_isolated` strategy
- [x] `clear-lock` CLI command to remove stale lock files after a crash
- [x] Catch-up missed runs functionality
- [x] Schedule simulation/testing feature (simulate-missed command)
- [x] Optimize catch-up to run a single transfer for all missed windows (delta sync covers full backlog)
- [x] TROUBLESHOOTING.md documentation
- [x] Install scripts (install.ps1, install.sh)

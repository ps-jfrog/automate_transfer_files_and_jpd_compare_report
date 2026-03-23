# JFrog Transfer Automation

Automates daily delta syncs using `jf rt transfer-files`, generates a high-level
comparison report, and optionally sends notifications.

## Key features
- **Pre-flight connectivity check** — validates source↔target connectivity before every transfer; fails fast with actionable guidance if the data-transfer plugin is missing, network is blocked, or permissions are insufficient
- Daily scheduler with non-overlapping runs
- Two transfer modes: `single_command` (default) and `per_repo` (with batching, stuck detection)
- Per-repo isolated CLI home directories (optional)
- Windows-friendly report generation (no bash/jq dependency)
- Uses JFrog CLI config to discover URL and access tokens
- Background execution support
- Dry-run mode for testing
- Resume stopped transfers
- Continuous monitoring mode

## Getting started
- **Installation**: See [INSTALL.md](INSTALL.md) for detailed installation and service setup instructions.
- **Quick start**: See [QUICKSTART.md](QUICKSTART.md) for common CLI usage examples (run-once, scheduler, validate, etc.).
- **Beyond the quick start**: `QUICKSTART.md` focuses on typical command-line flows, not every use case. For fuller coverage, also read [SCHEDULER_GUIDE.md](SCHEDULER_GUIDE.md) (scheduled runs and testing catch-up), [TROUBLESHOOTING.md](TROUBLESHOOTING.md), and the commented [config.sample.yaml](config.sample.yaml) (all settings, path resolution, notifications, and report options).

## Dependencies

Core dependencies are listed in `requirements.txt`:
- `pyyaml` - YAML configuration parsing
- `requests` - HTTP client for Artifactory REST API
- `portalocker` - Cross-platform file locking

Install dependencies:
```bash
# Recommended: Install as editable package (includes dependencies)
pip install -e .

# Or install dependencies only
pip install -r requirements.txt
```

For development dependencies (pytest), see `pyproject.toml`.

## Commands

- `validate` - Validate configuration and JFrog CLI setup
- `run-once` - Run transfer and report once
- `status` - Check transfer status
- `stop` - Stop running transfer
- `resume` - Resume a stopped transfer
- `monitor` - Continuously monitor transfer progress
- `report` - Generate comparison report only
- `scheduler` - Run daily scheduled transfers

## Options

- `--dry-run` - Show what would be executed without running
- `--background` - Run in background (detach from terminal)
- `--verbose` - Enable verbose logging

## Transfer Modes

The `transfer.mode` configuration option controls how repositories are transferred:

### `single_command` (Default)

Runs a single `jf rt transfer-files` command with all repositories included in one command.

**Best for:**
- Small to medium number of repositories
- Simple, fast transfers
- When you don't need per-repo isolation

**Example:**
```yaml
transfer:
  mode: "single_command"
  include_repos_file: "repos.txt"
  threads: 8
```

**How it works:**
- Executes: `jf rt transfer-files <source> <target> --include-repos "repo1;repo2;repo3;..."`
- All repositories transferred in one operation
- Single JFrog CLI process

### `per_repo`

Runs a separate `jf rt transfer-files` command for each repository, with advanced features.

**Best for:**
- Large numbers of repositories (hundreds or thousands)
- When you need per-repo error isolation
- When you need stuck detection and automatic recovery
- When you need isolated CLI home directories

**Example:**
```yaml
transfer:
  mode: "per_repo"
  include_repos_file: "repos.txt"
  batch_size: 4                    # Process 4 repos at a time
  stuck_timeout_seconds: 600       # Restart if stuck for 10 minutes
  jfrog_cli_home_strategy: "per_repo_isolated"  # Optional isolation
  threads: 8
```

**Features:**
- **Batching**: Processes repositories in parallel batches (configurable via `batch_size`)
- **Stuck Detection**: Monitors log file modification times and automatically restarts stuck transfers (max 3 attempts)
- **Error Isolation**: Failed repositories don't block others
- **Isolated CLI Home**: Optional per-repo isolated `JFROG_CLI_HOME_DIR` to prevent conflicts

**How it works:**
- Executes one `jf rt transfer-files` command per repository
- Processes repositories in batches (e.g., 4 at a time)
- Monitors each transfer for completion or stuck state
- Automatically restarts stuck transfers

## JFrog CLI Home Strategy

The `jfrog_cli_home_strategy` option controls how JFrog CLI home directories are managed (only applies to `per_repo` mode):

### `default`

Uses the default JFrog CLI home directory (typically `~/.jfrog` or `%USERPROFILE%\.jfrog`).

**Use when:**
- You don't need isolation between repository transfers
- All repositories can share the same CLI configuration and state

### `per_repo_isolated`

Creates a separate `JFROG_CLI_HOME_DIR` for each repository transfer.

**Use when:**
- You need to prevent conflicts between concurrent transfers
- Different repositories may have different CLI configurations
- You want complete isolation between repository transfers

**How it works:**
- Creates persistent isolated directories: `<output_dir>/cli_homes/<repo-name>/`
- Server configs are imported from the default CLI home (`~/.jfrog`) via `jf c export/import`
- The bootstrap validates that both the URL **and** access token are present; incomplete configs trigger a fresh import
- If the pre-flight connectivity check fails from an isolated home, the automation **automatically re-bootstraps** — deletes the stale home, re-imports, and retries
- Prevents state conflicts when processing multiple repositories in parallel
- CLI homes persist across runs, preserving JFrog CLI transfer state for proper delta sync

**Example:**
```yaml
transfer:
  mode: "per_repo"
  jfrog_cli_home_strategy: "per_repo_isolated"
  batch_size: 4
```

**Note:** This option only has effect when `transfer.mode` is set to `"per_repo"`. In `single_command` mode, it is ignored.

### Directory layout

The `output_dir` (configured via `report.output_dir`, default `./runs`) contains both persistent state and per-run artifacts. The layout differs depending on the `jfrog_cli_home_strategy`:

#### With `jfrog_cli_home_strategy: "default"`

All repos share the system-wide JFrog CLI home (`~/.jfrog`). Delta sync state is stored there automatically by the JFrog CLI.

```
<output_dir>/                              (e.g. ./runs/)
├── .lock                                  ← run lock file
├── current_run.json                       ← current run status
├── last_run_time.json                     ← last successful run timestamp
├── next_scheduled_run.json                ← next scheduled run time
│
├── 20260127_214200/                       ← per-run directory (one per run)
│   ├── run.log                            ← run log
│   ├── reports/
│   │   ├── comparison-20260127_214200.txt  ← comparison report
│   │   ├── comparison-summary.json
│   │   ├── source-storageinfo-*.json
│   │   └── target-storageinfo-*.json
│   └── logs/                              ← per-repo transfer logs (per_repo mode only)
│       ├── repo-a.log
│       └── repo-b.log
│
└── 20260128_214200/                       ← next run (same structure)
    └── ...
```

Delta sync state: `~/.jfrog` (shared, persistent, managed by JFrog CLI)

#### With `jfrog_cli_home_strategy: "per_repo_isolated"`

Each repo gets its own persistent CLI home under `<output_dir>/cli_homes/`. Transfer state is preserved across runs for proper delta sync, while each repo remains isolated for concurrency safety.

```
<output_dir>/                              (e.g. ./runs/)
├── .lock
├── current_run.json
├── last_run_time.json
├── next_scheduled_run.json
│
├── cli_homes/                             ← persistent CLI homes (delta sync state)
│   ├── repo-a/                            ← JFROG_CLI_HOME_DIR for repo-a
│   │   └── .jfrog/                        ← JFrog CLI state (transfer history, etc.)
│   └── repo-b/                            ← JFROG_CLI_HOME_DIR for repo-b
│       └── .jfrog/
│
├── 20260127_214200/                       ← per-run directory (one per run)
│   ├── run.log
│   ├── reports/
│   │   ├── comparison-20260127_214200.txt
│   │   ├── comparison-summary.json
│   │   ├── source-storageinfo-*.json
│   │   └── target-storageinfo-*.json
│   └── logs/
│       ├── repo-a.log
│       └── repo-b.log
│
└── 20260128_214200/                       ← next run (same structure)
    └── ...
```

Delta sync state: `<output_dir>/cli_homes/<repo>/` (per-repo, persistent across runs)

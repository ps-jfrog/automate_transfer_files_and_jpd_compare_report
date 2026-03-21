# Quickstart

## Prerequisites
- Python 3.9+
- JFrog CLI (`jf`) on PATH
- JFrog CLI configured with source/target server IDs

## Install
For detailed installation instructions, including running as a background service, see [INSTALL.md](INSTALL.md).

Quick install:
```bash
# Windows
.\scripts\install.ps1

# Linux/macOS
./scripts/install.sh

# Or manually
pip install -e .
```

## Configure
Copy `config.sample.yaml` to `config.yaml` and update values.

### Minimum Configuration (Recommended)

Most customers use `per_repo` mode with isolated CLI homes. At a minimum, configure these settings:

```yaml
schedule:
  timezone: "America/Los_Angeles"        # Your IANA timezone
  start_time: "01:00"                    # Daily start time (24-hour HH:MM)

jfrog:
  jfrog_cli_path: "jf"                   # Path to JFrog CLI
  source_server_id: "source-server"      # jf config server ID for source
  target_server_id: "target-server"      # jf config server ID for target

transfer:
  include_repos_file: "all_local_repos_in_prod.txt"  # File with repo keys (one per line)
  mode: "per_repo"                       # Per-repo transfers with isolation
  threads: 8                             # Transfer worker threads
  batch_size: 4                          # Repos processed in parallel
  stuck_timeout_seconds: 600             # Restart if stuck for 10 minutes
  jfrog_cli_home_strategy: "per_repo_isolated"  # Isolated CLI home per repo
  cli_log_level: "INFO"

report:
  enabled: true
  output_dir: "./runs"
  detailed_comparison: true
  repos_file_for_comparison: "all_local_repos_in_prod.txt"
```

> **Path resolution:** All relative paths in the config are resolved relative
> to the **directory containing the YAML file**, not your shell's current
> working directory.  For example, if the config lives at
> `/opt/transfer/config.yaml` and you set `output_dir: "./runs"`, reports are
> written to `/opt/transfer/runs/` regardless of where you run the command.
> This applies to `transfer.include_repos_file`, `report.output_dir`, and
> `report.repos_file_for_comparison`.  Use absolute paths to bypass this.

All other settings have sensible defaults. See `config.sample.yaml` for the full list with comments.

### Transfer Mode Selection

Choose the appropriate transfer mode based on your needs:

**Single Command Mode** - Best for small to medium repository sets:
```yaml
transfer:
  mode: "single_command"
```

**Per-Repo Mode (Recommended)** - Best for large repository sets with advanced features:
```yaml
transfer:
  mode: "per_repo"
  batch_size: 4
  stuck_timeout_seconds: 600
  jfrog_cli_home_strategy: "per_repo_isolated"
```

See `README.md` for detailed documentation on transfer modes and `jfrog_cli_home_strategy`.

### Changing Transfer Threads Dynamically

The `transfer.threads` setting controls how many worker threads JFrog CLI uses for
`transfer-files`. The automation applies this setting via `jf rt transfer-settings`
before each transfer starts.

**Between runs** — edit `config.yaml` and change the `transfer.threads` value. The new
thread count takes effect on the next `run-once` or scheduled run.

**During a running transfer** — use the built-in `update-threads` command. It re-reads
the config and applies the thread setting to the default CLI home and/or every
per-repo isolated CLI home directory automatically:

```bash
# Update threads to the value in config.yaml (edit config.yaml first)
jfrog-transfer-automation update-threads --config config.yaml

# Or override with a specific value without editing config.yaml
jfrog-transfer-automation update-threads --config config.yaml --threads 16
```

When using `per_repo_isolated`, the command discovers all CLI home directories under
`<output_dir>/cli_homes/*/` and updates each one. Example output:

```
Updating transfer threads to 16 (strategy: per_repo_isolated)
  ✓ libs-release-local: threads set to 16
  ✓ libs-snapshot-local: threads set to 16
  ✓ plugins-release-local: threads set to 16

Successfully updated threads to 16 across 3 CLI home(s).
```

> **Note:** Thread changes take effect on the next transfer chunk, not immediately
> on in-flight chunks.

**Mid-run override persistence:** When you use `update-threads` during a run,
the override is preserved for the remainder of that run.  New batches will
**not** reset threads back to the `config.yaml` value — the config value is
only applied once per CLI home (the first time it is used in a run).  If a
stuck transfer is restarted, the override is also preserved.

### Building the Repository List

The `transfer.include_repos_file` setting points to a text file with one repository key per line. Use the JFrog CLI to generate this list from your source Artifactory.

**Get local repos** (with `jq`):
```bash
jf rt curl -X GET "/api/repositories?type=local" --server-id=source | \
  jq -r '.[] | .key' >> all_local_repos_in_source.txt
```

**Without `jq`** (any of these alternatives work):
```bash
# Option 1: grep + cut
jf rt curl -X GET "/api/repositories?type=local" -s --server-id=source | \
  grep '"key"' | cut -d'"' -f4 >> all_local_repos_in_source.txt

# Option 2: grep + sed
jf rt curl -X GET "/api/repositories?type=local" -s --server-id=source | \
  grep -o '"key" *: *"[^"]*"' | \
  sed -E 's/"key" *: *"([^"]*)"/\1/' >> all_local_repos_in_source.txt

# Option 3: awk
jf rt curl -X GET "/api/repositories?type=local" -s --server-id=source | \
  awk -F'"key"[[:space:]]*:[[:space:]]*' '{for (i=2; i<=NF; i++) print $i}' | \
  awk -F'"' '{print $2}' >> all_local_repos_in_source.txt
```

**Sort the list** (recommended for consistency):
```bash
sort -o all_local_repos_in_source.txt all_local_repos_in_source.txt
```

**Exclude specific repos** (e.g., customer-managed repos you don't want to transfer):
```bash
comm -23 <(sort all_local_repos_in_source.txt) \
         <(sort exclude_these_repos.txt) > repos_to_transfer.txt
```

**For federated repos**, use `type=federated` instead:
```bash
jf rt curl -X GET "/api/repositories?type=federated" --server-id=source | \
  jq -r '.[] | .key' >> all_federated_repos_in_source.txt

sort -o all_federated_repos_in_source.txt all_federated_repos_in_source.txt
```

Then reference the generated file in your config:
```yaml
transfer:
  include_repos_file: "all_local_repos_in_source.txt"
```

## Basic Usage
### Dry run (test without executing)
```bash
jfrog-transfer-automation run-once --config config.yaml --dry-run
```


### Run once
```bash
jfrog-transfer-automation run-once --config /Users/sureshv/mycode/ps-jfrog/automate_transfer_files_and_jpd_compare_report/test_schedule/config.yaml
```



### Run in background
```bash
jfrog-transfer-automation run-once --config config.yaml --background
```

### Check status
```bash
jfrog-transfer-automation status --config config.yaml
```

### Stop transfer
```bash
jfrog-transfer-automation stop --config config.yaml
```

### Resume stopped transfer
```bash
jfrog-transfer-automation resume --config config.yaml
```

### Monitor transfer progress
```bash
jfrog-transfer-automation monitor --config config.yaml --interval 10
```

### Update transfer threads (even while running)
```bash
# Use thread count from config.yaml
jfrog-transfer-automation update-threads --config config.yaml

# Override with a specific value
jfrog-transfer-automation update-threads --config config.yaml --threads 16
```

### Clear stale lock (after a crash)
```bash
jfrog-transfer-automation clear-lock --config config.yaml
```

### Generate report only
```bash
jfrog-transfer-automation report --config config.yaml
```

## Running Commands Alongside a Transfer

While `run-once` (or `scheduler`) is actively running a transfer, you can open
separate terminal windows and run certain commands.  The table below summarises
what works and what does not:

| Command | Works alongside `run-once`? | Notes |
|---|---|---|
| `monitor` | **Yes** | Read-only status queries against each CLI home |
| `status` | **Yes** | One-shot version of `monitor` |
| `update-threads` | **Yes** | Safe mid-transfer; takes effect on the next chunk |
| `stop` | **Yes** | Signals JFrog to stop; `run-once` stops remaining batches and exits |
| `report` | **Yes** | Generates a comparison report independently |
| `resume` | **No** | Blocked by the run lock — use after `run-once` finishes |
| `run-once` | **No** | Blocked by the run lock while another run is active |

### Typical multi-terminal workflow

```text
Terminal 1 — start the transfer
$ jfrog-transfer-automation run-once --config config.yaml

Terminal 2 — watch progress (Ctrl+C stops monitoring, not the transfer)
$ jfrog-transfer-automation monitor --config config.yaml

Terminal 3 — adjust threads mid-transfer
$ jfrog-transfer-automation update-threads --config config.yaml --threads 6

Terminal 4 — gracefully stop when needed
$ jfrog-transfer-automation stop --config config.yaml
```

### What happens when you run `stop`

When you run `stop` from another terminal while `run-once` is active:

1. `stop` sends `jf rt transfer-files --stop` to each per-repo CLI home and
   writes `status: stopped` to `current_run.json`.
2. The `run-once` process detects the stop signal, kills any active transfer
   processes in the current batch, and **skips all remaining batches**.
3. Report generation is **skipped** (the transfer was intentionally
   interrupted, so a partial-progress report is not generated).
4. `run-once` writes `status: stopped`, releases the lock, and exits.

> **Note:** When the transfer ends naturally (all batches complete) or is
> stopped by the configured `end_time`, the comparison report **is** generated
> as usual.  The report is only skipped when `stop` is explicitly invoked.

### Stop → Resume sequence

`resume` can only run **after** `run-once` has fully exited and released its
lock.  The correct sequence is:

1. Run `stop` from another terminal — this tells the JFrog platform to halt
   the transfer.
2. Wait for the `run-once` process in Terminal 1 to exit (it will skip report
   generation, update status, and release the lock).
3. Now run `resume` to continue where the transfer left off:

```bash
jfrog-transfer-automation resume --config config.yaml
```

If you try to `resume` while `run-once` is still running you will see:

```
Run in progress (started at ...). Skipping.
```

If a crash left a stale lock behind (and no process is actually running), use
`clear-lock` first:

```bash
jfrog-transfer-automation clear-lock --config config.yaml
jfrog-transfer-automation resume --config config.yaml
```

## Transfer Outcome Reference

When a run finishes, the tool records a status in `current_run.json` and
decides whether to generate a comparison report and update the scheduler's
`last_run_time`.  The table below shows how each scenario is handled:

| Scenario | Status in `current_run.json` | Report generated? | `last_run_time` updated? |
|---|---|---|---|
| All repos transferred successfully | `completed` | Yes | Yes |
| Some repos failed (stuck after max restarts, exit code != 0) | `partial` | Yes | Yes |
| Configured `end_time` reached | `completed` | Yes | Yes |
| User ran `stop` from another terminal | `stopped` | **No** | **No** |

**Why `partial` still updates `last_run_time`:** JFrog's `transfer-files`
uses delta sync — the next scheduled run will automatically pick up whatever
was missed.  Keeping the timestamp current prevents the scheduler from
endlessly retrying the same window.  The `partial` status is preserved in
`current_run.json` so you can tell at a glance that not everything succeeded;
check the run log for details on which repos failed.

**Why `stopped` skips the report:** A user-initiated stop is an intentional
interruption.  The transfer was cut short on purpose, so generating a
partial-progress report is not useful.  Use `resume` after the run exits to
continue where it left off.

## Scheduler (daily)
```bash
jfrog-transfer-automation scheduler --config config.yaml
```

### Simulate missed schedule (testing)
```bash
# Simulate last run 2 days ago to test catch_up_if_missed
jfrog-transfer-automation simulate-missed --config config.yaml --days-ago 2
```

## Examples

### Test configuration
```bash
jfrog-transfer-automation validate --config config.yaml
```

### Dry run with verbose output
```bash
jfrog-transfer-automation run-once --config config.yaml --dry-run --verbose
```

### Background transfer with monitoring
```bash
# Start in background
jfrog-transfer-automation run-once --config config.yaml --background

# Monitor in another terminal
jfrog-transfer-automation monitor --config config.yaml
```

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
  threads: 256                             # Transfer worker threads per repo
  batch_size: 4                          # Repos processed in parallel
  max_total_threads: 1024                # Global safety cap (see thread tuning note below)
  adaptive_threads: false                # Redistribute freed threads (see thread tuning note below)
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

> **Thread tuning:** The `threads` × `batch_size` product determines total
> load on the source Artifactory. Use
> [`max_total_threads`](#controlling-total-thread-load-max_total_threads) to
> enforce a global safety cap, and
> [`adaptive_threads`](#adaptive-thread-redistribution-adaptive_threads) to
> automatically redistribute freed capacity when repos finish early.

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

### Pre-flight Connectivity Check

Before starting any transfer, the automation runs
`jf rt transfer-files --prechecks` to verify connectivity between the source
and target Artifactory servers.  This check runs automatically — no extra
configuration is needed.

If the pre-flight check **fails**, the transfer is **not attempted**:

- No data is transferred
- No comparison report is generated
- `current_run.json` is set to `status: "prechecks_failed"`
- The full `--prechecks` output is logged so you can diagnose the issue

Common causes of precheck failures:

| Cause | Fix |
|-------|-----|
| Data-transfer plugin not installed on source | Install the [data-transfer](https://docs.jfrog.com/integrations/docs/cli-for-jfrog-cloud-transfer) plugin |
| Network connectivity blocked between source and target | Check firewall rules, proxy settings |
| Access token lacks required permissions | Use an admin-scoped token |
| Server IDs misconfigured | Run `jf c show <server-id>` to verify |
| Stale/incomplete config in isolated CLI home (`per_repo_isolated`) | Config-copy bootstrap handles this — see below |

**`per_repo_isolated` config-copy bootstrap:** when using isolated CLI homes,
the automation bootstraps the **first** repo's CLI home via
`jf c export/import`, validates it with `--prechecks`, and then **copies**
the validated `jfrog-cli.conf` file to every other repo's CLI home.  This
guarantees all repos have identical, known-good credentials.  If a transfer
later fails with a `401` auth error, the config is re-copied and the transfer
retried once.  You can also manually clear all isolated homes with
`rm -rf runs/cli_homes/`.

> **Tip:** You can test the precheck manually with:
> ```bash
> jf rt transfer-files <source-server-id> <target-server-id> \
>     --include-repos "<any-repo>" --prechecks
> ```

### Limiting Transfer Duration with `end_time`

The `schedule.end_time` setting defines a daily cutoff time for transfers.
When set, any running transfer — whether started via `run-once`, `resume`,
or the `scheduler` — is **gracefully stopped** when the clock passes this time.

```yaml
schedule:
  start_time: "01:00"
  end_time: "05:00"        # stop transfers at 5:00 AM (set to null to disable)
  timezone: "America/Los_Angeles"
```

**How it works:**

1. When a transfer starts, the automation computes an absolute cutoff
   timestamp from `end_time` in the configured `timezone`.
2. The monitoring loop checks the clock on every iteration
   (`poll_interval_seconds`).
3. When the cutoff is reached:
   - In **per-repo mode**: all active transfer processes in the current
     batch are killed immediately, and remaining batches are skipped.
   - In **single-command mode**: `jf rt transfer-files --stop` is sent.
4. A comparison **report is still generated** (unlike a user-invoked `stop`),
   and `last_run_time` is updated so the scheduler knows the window was
   covered.
5. The transfer can be **resumed** later — JFrog CLI's transfer state tracks
   which files were already sent, so the next `run-once` or scheduled run
   picks up where this one left off.

> **Tip:** If you only want to run transfers during off-peak hours
> (e.g. 1 AM–5 AM), set `start_time: "01:00"` and `end_time: "05:00"`.
> The scheduler will start a transfer at 1 AM and automatically stop it
> at 5 AM if it hasn't finished.  The next night's run resumes from
> where the previous one stopped.

Set `end_time: null` (or omit it) to let transfers run to completion
with no time limit.

### Changing Transfer Threads Dynamically

The `transfer.threads` setting controls how many worker threads JFrog CLI uses
for each `transfer-files` process. By default JFrog CLI uses **8 threads**.
You can increase this value (e.g. 16, 24, up to a maximum of 1024) or decrease
it depending on the capacity of your source instance. See the JFrog documentation
on [Controlling File Transfer Speed](https://docs.jfrog.com/integrations/docs/cli-for-jfrog-cloud-transfer#controlling-file-transfer-speed)
for full details.

> **Important — monitor your source instance.**  While a transfer is running,
> monitor the **CPU, memory, and network utilization** on your source Artifactory.
> Increasing threads speeds up the transfer but places additional load on the
> source. Reducing threads does the opposite. We recommend **increasing
> gradually** and observing the impact before raising the value further.

The automation applies this setting via `jf rt transfer-settings` before each
transfer starts. You can adjust the thread count in two ways:

**Between runs** — edit `config.yaml` and change the `transfer.threads` value.
The new thread count takes effect on the next `run-once` or scheduled run.
You can re-run `jfrog-transfer-automation run-once` as many times as needed;
each run resumes from where the previous one left off.

**During a running transfer** — open a **new terminal window on the same
machine** (as the same user that started the transfer) and use the built-in
`update-threads` command:

```bash
# Update threads to the value in config.yaml (edit config.yaml first)
jfrog-transfer-automation update-threads --config config.yaml

# Or override with a specific value without editing config.yaml
jfrog-transfer-automation update-threads --config config.yaml --threads 16
```

When using `per_repo_isolated`, the command discovers all CLI home directories
under `<output_dir>/cli_homes/*/` and updates each one. Example output:

```
Updating transfer threads to 16 (strategy: per_repo_isolated)
  ✓ libs-release-local: threads set to 16
  ✓ libs-snapshot-local: threads set to 16
  ✓ plugins-release-local: threads set to 16

Successfully updated threads to 16 across 3 CLI home(s).
```

> **Note:** Thread changes take effect on the next transfer chunk, not
> immediately on in-flight chunks.

**Mid-run override persistence:** When you use `update-threads` during a run,
the override is preserved for the remainder of that run. New batches will
**not** reset threads back to the `config.yaml` value — the config value is
only applied once per CLI home (the first time it is used in a run). If a
stuck transfer is restarted, the override is also preserved.

#### Controlling Total Thread Load (`max_total_threads`)

In `per_repo` mode the automation launches up to `batch_size` transfer
processes **in parallel**. Without any cap, the total thread load hitting your
source Artifactory equals **`batch_size` × `threads`**. To prevent this from
overwhelming the source instance, set `max_total_threads` in `config.yaml`:

```yaml
transfer:
  threads: 256           # desired per-repo threads
  batch_size: 4          # repos transferred in parallel
  max_total_threads: 1024  # safety cap on total concurrent threads
```

The automation calculates the effective per-repo threads as:

```
effective_threads = min(threads, max_total_threads ÷ active_repos_in_batch)
```

| `threads` | `batch_size` | `max_total_threads` | Effective per-repo | Total load |
|-----------|-------------|---------------------|--------------------|------------|
| 256       | 4           | 1024                | 256                | 1024       |
| 512       | 4           | 1024                | 256 (capped)       | 1024       |
| 256       | 8           | 1024                | 128 (capped)       | 1024       |
| 256       | 4           | *null*              | 256 (no cap)       | 1024       |
| 8         | 4           | 1024                | 8 (below cap)      | 32         |

Set `max_total_threads: null` (or omit it) to disable the cap entirely.

> **Tip — choosing `threads` vs `max_total_threads`:**
>
> - **Without adaptive redistribution** (default): set `threads` to your
>   desired per-repo count (e.g. 256) and `max_total_threads` as the global safety
>   cap (e.g. 1024). Each repo gets exactly 256 threads.
> - **With `adaptive_threads: true`**: set `threads` equal to
>   `max_total_threads` (e.g. both 1024). This allows the automation to
>   boost remaining repos as others finish, keeping the total load close to
>   the global safety cap (e.g. 1024) at all times.
>
> Monitor CPU, memory, and network on the source instance and adjust as needed.

#### Adaptive Thread Redistribution (`adaptive_threads`)

When a batch starts with 4 repos but 2 finish early, the remaining 2 repos
are still running at their original thread count — wasting half the available
capacity. Enable `adaptive_threads` to automatically boost the remaining
repos so the total load stays close to `max_total_threads`.

> **Key concept:** `transfer.threads` is the **per-repo ceiling** — no single
> repo will ever exceed this value. `max_total_threads` is the **global
> ceiling** across all concurrent repos. Adaptive redistribution can boost a
> repo up to `min(threads, max_total_threads ÷ active_repos)`. For the
> boost to have any effect, `threads` must be **greater than**
> `max_total_threads ÷ batch_size`.

```yaml
transfer:
  threads: 1024          # per-repo ceiling (high enough to allow boosting)
  batch_size: 4
  max_total_threads: 1024  # global ceiling
  adaptive_threads: true   # redistribute freed threads to active repos
```

**How it works:**

1. A batch of 4 repos starts. Each gets `min(1024, 1024 ÷ 4) = 256` threads
   (total: 1024).
2. Two repos finish quickly.
3. The automation recalculates: `min(1024, 1024 ÷ 2) = 512`.
4. The remaining 2 repos are boosted to **512 threads each**, keeping the
   total at 1024.
5. When only 1 repo remains: `min(1024, 1024 ÷ 1) = 1024` — it gets the
   full capacity.

| Active repos | Calculation | Per-repo threads | Total | What happened |
|-------------|-------------|-----------------|-------|---------------|
| 4 (start)   | min(1024, 1024÷4) | 256        | 1024  | Batch launched |
| 2 (after 2 finish) | min(1024, 1024÷2) | 512  | 1024  | Threads redistributed |
| 1 (after 3 finish) | min(1024, 1024÷1) | 1024 | 1024  | Full capacity to last repo |

> **Why not `threads: 256`?** With `threads: 256` and `max_total_threads: 1024`,
> `min(256, 1024 ÷ 2) = 256` — the per-repo ceiling prevents any boost.
> Adaptive redistribution has no effect when `threads ≤ max_total_threads ÷ batch_size`.
> Set `threads` equal to (or higher than) `max_total_threads` to get the full benefit.

> **Note:** `adaptive_threads` requires `max_total_threads` to be set.
> The redistribution takes effect on the next transfer chunk; in-flight
> chunks continue at the previous rate.

> **Per-repo parallel mode — load multiplier warning**
>
> When running with `transfer.mode: "per_repo"` and
> `transfer.jfrog_cli_home_strategy: "per_repo_isolated"`, the automation
> launches up to `batch_size` `transfer-files` processes **in parallel**.
> Each process uses its effective thread count independently, so the
> combined load on your source Artifactory can reach
> **`max_total_threads`** (or `batch_size` × `threads` if no cap is set).
>
> Monitoring CPU, memory, and network on the source is **critical** in
> this mode to avoid degrading the performance of your production Artifactory.
> Start with a conservative `max_total_threads` value and increase only after
> confirming the source instance can handle the combined load.

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
| Pre-flight check failed (`--prechecks`) | `prechecks_failed` | **No** | **No** |
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

---

## Running the Integration Test

An end-to-end integration test exercises the full workflow — seeding Docker
images into the source repos, running transfers with concurrent `monitor` /
`update-threads`, and testing the `stop` → `resume` sequence — against live
Artifactory instances.

### Prerequisites

- JFrog CLI configured with both source and target server IDs (e.g. `app1`,
  `app2`)
- Docker daemon running
- `docker_image_generator.py` available (from
  [ps-jfrog/charts](https://github.com/ps-jfrog/charts/blob/master/ps/publish_to_artifactory/docker_publish))
- Repos in your `transfer.include_repos_file` exist in both source and target
- Data-transfer plugin installed on the source instance

### Install test dependencies

```bash
pip install pytest
```

### Run all three stages (seed + transfer + stop/resume)

All `pytest` commands must be run **from the `jfrog-transfer-automation/`
directory** so that pytest discovers the `tests/integration/conftest.py` that
registers the custom CLI options (`--config`, `--docker-generator`, etc.):

```bash
cd jfrog-transfer-automation/

pytest tests/integration/test_e2e_transfer_workflow.py -v -s \
    --config /path/to/test_schedule/config.yaml \
    --docker-generator /path/to/docker_image_generator.py \
    --docker-username app1user
```
Example:
```
pytest tests/integration/test_e2e_transfer_workflow.py -v -s \
    --config ../test_schedule/config.yaml \
    --docker-generator /Users/sureshv/mycode/github-sv/utils/publish_to_artifactory/docker_publish/docker_image_generator.py \
    --docker-username app1user \
    --image-count 2 \
    --image-size-mb 1
```

### Skip the seed stage (data already exists)

```bash
pytest tests/integration/test_e2e_transfer_workflow.py -v -s \
    --config /path/to/test_schedule/config.yaml \
    -k "not seed"
```

### Run only the stop/resume test

```bash
pytest tests/integration/test_e2e_transfer_workflow.py -v -s \
    --config /path/to/test_schedule/config.yaml \
    -k "TestStopAndResume"
```

### Customise image size and count

```bash
pytest tests/integration/test_e2e_transfer_workflow.py -v -s \
    --config config.yaml \
    --docker-generator /path/to/docker_image_generator.py \
    --image-count 2 \
    --image-size-mb 5
```

### Test stages

The test mirrors the "Typical multi-terminal workflow" documented above.

| Stage | Test class | What it does |
|-------|-----------|-------------|
| 1. Seed | `TestSeedData` | Publishes Docker images to every source repo |
| 2. Workflow | `TestMultiTerminalWorkflow` | `run-once` → `monitor` → `update-threads` → `stop` → verify clean exit → `resume` |

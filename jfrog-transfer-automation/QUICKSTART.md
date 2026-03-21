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
  include_repos_file: "repos.txt"        # File with repo keys (one per line)
  mode: "per_repo"                       # Per-repo transfers with isolation
  threads: 8                             # Transfer worker threads
  batch_size: 4                          # Repos processed in parallel
  stuck_timeout_seconds: 600             # Restart if stuck for 10 minutes
  jfrog_cli_home_strategy: "per_repo_isolated"  # Isolated CLI home per repo
  cli_log_level: "INFO"                  # JFrog CLI log level
```

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

### Run once
```bash
jfrog-transfer-automation run-once --config config.yaml
```

### Dry run (test without executing)
```bash
jfrog-transfer-automation run-once --config config.yaml --dry-run
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

### Generate report only
```bash
jfrog-transfer-automation report --config config.yaml
```

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

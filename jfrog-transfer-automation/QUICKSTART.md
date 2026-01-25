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

### Transfer Mode Selection

Choose the appropriate transfer mode based on your needs:

**Single Command Mode (Default)** - Best for small to medium repository sets:
```yaml
transfer:
  mode: "single_command"
```

**Per-Repo Mode** - Best for large repository sets with advanced features:
```yaml
transfer:
  mode: "per_repo"
  batch_size: 4
  stuck_timeout_seconds: 600
  jfrog_cli_home_strategy: "per_repo_isolated"  # Optional: for isolation
```

See `README.md` for detailed documentation on transfer modes and `jfrog_cli_home_strategy`.

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

# Troubleshooting Guide

Common issues and solutions for `jfrog-transfer-automation`.

## Authentication Issues

### Error: "Server ID not found in JFrog CLI"

**Problem**: The configured `source_server_id` or `target_server_id` doesn't exist in JFrog CLI config.

**Solution**:
1. List configured servers: `jf c show`
2. Add missing server: `jf c add <server-id>`
3. Verify: `jf c export <server-id>`

### Error: "Failed to export JFrog CLI config"

**Problem**: CLI config export failed or returned invalid data.

**Solution**:
- Ensure JFrog CLI is properly configured
- Check `jf c export <server-id>` works manually
- Use explicit `source_url`/`target_url` and `source_access_token`/`target_access_token` in config if CLI export fails

## Transfer Issues

### Pre-flight connectivity check failed (`prechecks_failed`)

**Problem**: The automation runs `jf rt transfer-files --prechecks` before every
transfer to verify source↔target connectivity.  If this check fails, no
transfer is attempted and `current_run.json` shows `status: "prechecks_failed"`.

**Common causes**:
- The **data-transfer plugin** is not installed on the source Artifactory
- Network connectivity between source and target is **blocked** (firewall, proxy)
- The access token **lacks admin permissions** on source or target
- The source or target **server ID is misconfigured** in JFrog CLI

**Diagnosis steps**:

```bash
# 1. Verify server configs
jf c show <source-server-id>
jf c show <target-server-id>

# 2. Run the precheck manually to see the full output
jf rt transfer-files <source-server-id> <target-server-id> \
    --include-repos "<any-repo>" --prechecks

# 3. If using per_repo_isolated strategy, test from an isolated CLI home
JFROG_CLI_HOME_DIR=runs/cli_homes/<repo> \
    jf rt transfer-files <source-server-id> <target-server-id> \
    --include-repos "<repo>" --prechecks
```

**Solution**: fix the underlying connectivity or permission issue, then re-run
`run-once`.  The automation will repeat the precheck automatically.

### Transfer fails immediately

**Problem**: `jf rt transfer-files` command fails.

**Solution**:
- Verify JFrog CLI is in PATH: `jf --version`
- Check server IDs are correct
- Verify network connectivity to source/target Artifactory
- Check permissions for transfer operations
- Review logs in `runs/<timestamp>/run.log`

### Transfer appears stuck

**Problem**: Transfer doesn't progress (only in per_repo mode with stuck detection enabled).

**Solution**:
- Check `stuck_timeout_seconds` setting
- Review transfer logs for errors
- Use `jfrog-transfer-automation status` to check JFrog transfer status
- Manually check: `jf rt transfer-files --status`

### "Run in progress. Skipping."

**Problem**: Another run is already active (lock file exists).

**Solution**:
- Wait for the current run to complete, or stop it: `jfrog-transfer-automation stop --config config.yaml`
- If the process crashed and left a stale lock, use the built-in command to clean up:
  ```bash
  jfrog-transfer-automation clear-lock --config config.yaml
  ```
  This verifies no process actually holds the lock before removing it, and resets
  `current_run.json` if it still shows "running".
- As a last resort, remove the lock file manually:
  ```bash
  rm ./runs/.lock
  rm ./runs/current_run.json   # optional, to reset run state
  ```

## Schedule Issues

### Scheduler doesn't run at expected time

**Problem**: Scheduled runs don't start.

**Solution**:
- Verify `schedule.start_time` format (HH:MM, 24-hour)
- Check timezone setting matches your system
- Ensure scheduler process is running
- Check logs for errors

### Missed runs not caught up

**Problem**: `catch_up_if_missed: true` but missed runs aren't executed.

**Solution**:
- Verify last run time is tracked (check `runs/last_run_time.json`)
- Use `simulate-missed` command to test: `jfrog-transfer-automation simulate-missed --config config.yaml --days-ago 2`
- Check scheduler logs for catch-up attempts

## Report Generation Issues

### "Storage calculation scheduled" but data not ready

**Problem**: Report shows incomplete data after `calculate_storage()`.

**Solution**:
- Increase `storage_calculation_wait_seconds` in config
- For large instances, may need 60-120 seconds
- Check Artifactory logs for calculation progress

### Report generation fails

**Problem**: API calls fail or return errors.

**Solution**:
- Verify `source_server_id` and `target_server_id` have API access
- Check network connectivity
- Verify SSL certificates if `verify_ssl: true`
- Review error messages in logs

### Detailed comparison fails

**Problem**: `detailed_comparison: true` but report generation fails.

**Solution**:
- Ensure `repos_file_for_comparison` exists and is readable
- Verify repos in file exist in both source and target
- Check AQL query permissions if `enable_aql_queries: true`
- Review error logs for specific failures

## Configuration Issues

### Config file not found

**Problem**: `--config` path doesn't exist.

**Solution**:
- Use absolute path or relative to current directory
- Verify file exists: `ls -l config.yaml`
- Check YAML syntax is valid

### Invalid config values

**Problem**: Config parsing fails or values are invalid.

**Solution**:
- Validate config: `jfrog-transfer-automation validate --config config.yaml`
- Check YAML indentation and syntax
- Verify required fields: `schedule.start_time`, `jfrog.source_server_id`, `jfrog.target_server_id`

## Windows-Specific Issues

### Background process doesn't detach

**Problem**: `--background` flag doesn't work on Windows.

**Solution**:
- Ensure running as administrator if needed
- Use Windows Task Scheduler instead
- Check process actually detaches (check Task Manager)

### Path issues

**Problem**: File paths don't work on Windows.

**Solution**:
- Use forward slashes or raw strings: `r"C:\path\to\file"`
- Avoid spaces in paths or quote them
- Use `Path` objects (handled automatically in code)

## Performance Issues

### Transfer is slow

**Problem**: Transfers take longer than expected.

**Solution**:
- Increase `transfer.threads` (but monitor system resources)
- For per_repo mode, adjust `batch_size`
- Check network bandwidth
- Review JFrog transfer logs for bottlenecks

### Report generation is slow

**Problem**: Reports take a long time to generate.

**Solution**:
- Disable `enable_aql_queries` if not needed (AQL queries are slow)
- Reduce number of repos in `repos_file_for_comparison`
- Increase `storage_calculation_wait_seconds` appropriately

## Collecting Logs for JFrog Professional Services

Please collect the artifacts described below.
Two common scenarios are covered — use whichever applies (or both).

### Understanding the two log levels

| Setting | What it controls | Where logs appear |
|---------|-----------------|-------------------|
| `--verbose` flag | The **automation tool's** own Python logging (DEBUG level) — config resolution, API URLs, orchestration decisions | `runs/<timestamp>/run.log` and console |
| `transfer.cli_log_level: "DEBUG"` in config | The **JFrog CLI** process logging — detailed transfer-files protocol messages, upload/download progress, retries | `runs/<timestamp>/logs/<repo>.log` (per-repo logs) |

For most issues you need **both**: `--verbose` shows what the automation decided
to do, and `cli_log_level: "DEBUG"` shows what the JFrog CLI actually did.

---

### Scenario A: Transfer completes partially — repositories failed (exit code 1)

Repositories that finish with exit code 1 are logged as failed and marked in
`current_run.json` with status `"partial"`.

**Step 1 — Reproduce with full debug logging**

Set `cli_log_level` to `DEBUG` in your config file:

```yaml
transfer:
  cli_log_level: "DEBUG"   # captures detailed JFrog CLI output per repo
```

Then re-run with `--verbose`:

```bash
jfrog-transfer-automation run-once --config config.yaml --verbose
```

**Step 2 — Collect and send the following**

| # | Artifact | Location / command |
|---|----------|--------------------|
| 1 | **Full run directory** (zip) | `zip -r failed-run.zip runs/<timestamp>/` |
| 2 | **Orchestration log** | `runs/<timestamp>/run.log` |
| 3 | **Per-repo transfer logs** (especially failed repos) | `runs/<timestamp>/logs/<repo>.log` |
| 4 | **Run summary** | `runs/<timestamp>/summary.json` and `runs/current_run.json` |
| 5 | **Config file** (redact tokens) | Your `config.yaml` — replace any `access_token` values with `***` |
| 6 | **JFrog CLI version** | `jf --version` |
| 7 | **Server config check** | `jf c show <source-server-id>` and `jf c show <target-server-id>` |
| 8 | **Manual transfer test** for a failed repo | `jf rt transfer-files <source-server-id> <target-server-id> --include-repos "<failed-repo>"` |

> **Tip:** The per-repo logs at `runs/<timestamp>/logs/<repo>.log` are the most
> important file for diagnosing exit-code-1 failures. They contain the raw JFrog
> CLI output including any error messages, retry attempts, and transfer protocol
> details — but only at full detail when `cli_log_level` is set to `"DEBUG"`.

---

### Scenario B: Storage calculation fails with 401 Unauthorized

This error occurs during report generation when the automation calls
`POST /api/storageinfo/calculate` on the source or target Artifactory. The API
requires **admin-level permissions** on the access token.

**Step 1 — Verify credentials manually**

Run these commands and capture the output:

```bash
# Show configured servers (verify URL and server ID)
jf c show <source-server-id>
jf c show <target-server-id>

# Test the exact API that failed — storageinfo/calculate requires admin permissions
jf rt curl -X POST "/api/storageinfo/calculate" --server-id=<source-server-id>
jf rt curl -X POST "/api/storageinfo/calculate" --server-id=<target-server-id>

# Also test the read-only storage info endpoint
jf rt curl -X GET "/api/storageinfo" --server-id=<source-server-id>
jf rt curl -X GET "/api/storageinfo" --server-id=<target-server-id>

# Test repository listing
jf rt curl -X GET "/api/repositories?type=local" --server-id=<target-server-id>
```

**Step 2 — Reproduce with verbose logging**

`--verbose` is sufficient here (no need for `cli_log_level: "DEBUG"` since this
is a Python-side API call, not a JFrog CLI transfer):

```bash
jfrog-transfer-automation run-once --config config.yaml --verbose
```

**Step 3 — Collect and send the following**

| # | Artifact | Location / command |
|---|----------|--------------------|
| 1 | **Orchestration log** | `runs/<timestamp>/run.log` (with `--verbose`) |
| 2 | **Config file** (redact tokens) | Your `config.yaml` — replace any `access_token` values with `***` |
| 3 | **Output of `jf c show`** | For both source and target server IDs |
| 4 | **Output of `jf rt curl` commands** | All four commands from Step 1 above |
| 5 | **JFrog CLI version** | `jf --version` |
| 6 | **Token permissions** | Confirm whether the access token has **admin** scope on the target instance |

> **Common causes:**
> - The access token works for `transfer-files` (which uses the data-transfer
>   API) but lacks the **admin** privilege required by `storageinfo/calculate`.
> - The token has expired or been rotated since it was added to the CLI config.
> - The URL is a platform URL but the token is scoped to a different instance.

---

## Getting Help

1. Check logs: `runs/<timestamp>/run.log`
2. Run with `--verbose` for detailed output
3. Use `--dry-run` to test without executing
4. Review `current_run.json` for run state

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
- Check `runs/.lock` - if stale, remove it manually
- Check `runs/current_run.json` for run status
- Wait for current run to complete, or stop it: `jfrog-transfer-automation stop`

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

## Getting Help

1. Check logs: `runs/<timestamp>/run.log`
2. Run with `--verbose` for detailed output
3. Use `--dry-run` to test without executing
4. Review `current_run.json` for run state

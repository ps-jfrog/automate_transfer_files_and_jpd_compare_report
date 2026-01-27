# JFrog Transfer Automation - Scheduler Guide

This guide explains how to use the `jfrog-transfer-automation scheduler` command to run automated daily transfers between JFrog Artifactory instances.

## Overview

The scheduler command runs continuously and automatically triggers transfers at scheduled times. It:

- Runs transfers at configured daily schedule windows
- Handles missed runs with catch-up functionality (optional)
- Prevents overlapping runs using file-based locking
- Persists the next scheduled run time for monitoring
- Logs all activities for troubleshooting

## Configuration

The scheduler behavior is controlled by the `schedule` section in your `config.yaml`:

```yaml
schedule:
  timezone: "America/Los_Angeles"      # Timezone for schedule (required)
  start_time: "21:42"                  # Daily start time in HH:MM format (required)
  end_time: null                        # Optional: Daily end time (null = no end time)
  run_on_startup: false                 # Run immediately when scheduler starts (optional)
  catch_up_if_missed: true              # Automatically catch up missed runs (optional)
```

### Configuration Options Explained

- **`timezone`**: IANA timezone name (e.g., "America/Los_Angeles", "UTC", "Europe/London")
- **`start_time`**: Daily transfer start time in 24-hour format (e.g., "21:42" for 9:42 PM)
- **`end_time`**: Optional end time for the schedule window. If `null`, transfers can run indefinitely
- **`run_on_startup`**: If `true`, runs a transfer immediately when the scheduler starts, then continues with scheduled runs
- **`catch_up_if_missed`**: If `true`, automatically detects and runs transfers for missed schedule windows when the scheduler starts

## Running the Scheduler

### Basic Usage

```bash
jfrog-transfer-automation scheduler --config <path-to-config.yaml> [--verbose]
```

### Example

```bash
jfrog-transfer-automation scheduler --config test_schedule/config.yaml --verbose
```

### Options

- **`--config`** (required): Path to your configuration YAML file
- **`--verbose`**: Enable verbose logging for detailed troubleshooting

### Running as a Background Service

For production use, run the scheduler as a system service (systemd on Linux, launchd on macOS, or Windows Service). See `INSTALL.md` for detailed service setup instructions.

### What Happens When You Start the Scheduler

1. **Catch-up Check** (if `catch_up_if_missed: true`):
   - Checks for missed schedule windows since the last successful run
   - Automatically runs catch-up transfers for any missed windows
   - Logs the number of missed windows found

2. **Startup Run** (if `run_on_startup: true`):
   - Runs a transfer immediately
   - Then continues with scheduled runs

3. **Schedule Loop**:
   - Calculates the next schedule window
   - Logs the next scheduled run time
   - Waits until the scheduled time
   - Runs the transfer at the scheduled time
   - Repeats indefinitely

### Example Output

```
2026-01-26 22:16:03 INFO Next scheduled run at 2026-01-27 21:42:00-08:00 (in 84356 seconds)
2026-01-27 21:42:00 INFO Starting scheduled transfer at 2026-01-27 21:42:00-08:00
2026-01-27 21:42:00 INFO Lock acquired successfully
2026-01-27 21:42:00 INFO Starting transfer...
...
```

## Monitoring the Scheduler

### Check Next Scheduled Run

The scheduler saves the next scheduled run time to:
```
<output_dir>/next_scheduled_run.json
```

You can view this file to see when the next transfer will run:

```bash
cat <output_dir>/next_scheduled_run.json
```

Example content:
```json
{
  "next_run": "2026-01-27T21:42:00-08:00",
  "updated_at": "2026-01-26T22:16:03.123456+00:00"
}
```

### Check Current Run Status

```bash
jfrog-transfer-automation status --config <path-to-config.yaml>
```

### View Logs

Logs are written to:
```
<output_dir>/<run-timestamp>/run.log
```

For example:
```bash
tail -f test_schedule/runs/20260127_214200/run.log
```

## Testing the Scheduler

Follow these steps to test the scheduler functionality:

### Test 1: Basic Scheduled Run

**Objective**: Verify the scheduler triggers transfers at the scheduled time.

**Steps**:

1. **Configure a near-future schedule**:
   - Edit your `config.yaml` to set `start_time` to approximately 10 minutes from now
   - For example, if it's 10:00 AM, set `start_time: "10:10"`

2. **Start the scheduler**:
   ```bash
   jfrog-transfer-automation scheduler --config test_schedule/config.yaml --verbose
   ```

3. **Upload a new artifact** (within the 10-minute window):
   - Upload a new Docker image or artifact to the source Artifactory instance (app2)
   - This ensures there's new content to transfer

4. **Wait for the scheduled time**:
   - The scheduler will log: `Next scheduled run at <time> (in <seconds> seconds)`
   - Wait for the scheduled time to arrive

5. **Verify the transfer**:
   - Check the logs to confirm the transfer started
   - Verify the artifact was transferred from app2 to app1
   - Check the transfer status:
     ```bash
     jfrog-transfer-automation status --config test_schedule/config.yaml
     ```

6. **Upload another artifact**:
   - Upload a different artifact to test subsequent scheduled runs

### Test 2: Catch-up Functionality

**Objective**: Verify the scheduler can catch up on missed runs.

**Steps**:

1. **Ensure catch-up is enabled** in your `config.yaml`:
   ```yaml
   schedule:
     catch_up_if_missed: true
   ```

2. **Simulate a missed run**:
   ```bash
   jfrog-transfer-automation simulate-missed --config test_schedule/config.yaml --days-ago 2 --verbose
   ```

   This command:
   - Simulates that the last run was 2 days ago
   - Calculates missed schedule windows
   - Attempts to run catch-up transfers for each missed window

3. **Verify catch-up execution**:
   - Check the logs for messages like:
     ```
     INFO Found 2 missed schedule window(s)
     INFO Attempting catch-up for window starting at <time>...
     ```
   - Verify that transfers were triggered for the missed windows
   - Confirm artifacts were transferred

4. **Upload a new artifact**:
   - Upload a new artifact to app2
   - Verify it gets transferred during the catch-up run

### Test 3: Run-on-Startup

**Objective**: Verify immediate execution when scheduler starts.

**Steps**:

1. **Enable run-on-startup** in your `config.yaml`:
   ```yaml
   schedule:
     run_on_startup: true
   ```

2. **Start the scheduler**:
   ```bash
   jfrog-transfer-automation scheduler --config test_schedule/config.yaml --verbose
   ```

3. **Verify immediate run**:
   - The scheduler should start a transfer immediately
   - Check logs for transfer activity right after startup
   - After the immediate run completes, it will continue with scheduled runs

## Troubleshooting

### Scheduler Not Running Transfers

1. **Check if scheduler is running**:
   ```bash
   ps aux | grep "jfrog-transfer-automation scheduler"
   ```

2. **Check for lock conflicts**:
   - If another process is holding the lock, scheduled runs will be skipped
   - Check for existing `runs/.lock` file
   - Review logs for "Run in progress. Skipping." messages

3. **Verify schedule configuration**:
   - Ensure `start_time` is correctly formatted (HH:MM)
   - Check timezone is valid (use IANA timezone names)
   - Verify `end_time` doesn't conflict with `start_time`

### Missed Runs Not Caught Up

1. **Verify catch-up is enabled**:
   ```yaml
   schedule:
     catch_up_if_missed: true
   ```

2. **Check last run time**:
   - Review `runs/last_run_time.json` to see when the last successful run occurred
   - Ensure there's a gap between last run and current time

3. **Check for stale run status**:
   - If `runs/current_run.json` shows `status: running` but the process isn't actually running, it may block catch-up
   - The scheduler automatically clears stale runs older than 24 hours

### Scheduler Exits Unexpectedly

1. **Check logs** for error messages:
   ```bash
   tail -100 <output_dir>/<latest-run>/run.log
   ```

2. **Verify configuration**:
   ```bash
   jfrog-transfer-automation validate --config <path-to-config.yaml>
   ```

3. **Check JFrog CLI setup**:
   - Ensure `jf c show` works for both source and target servers
   - Verify access tokens are valid

### Next Scheduled Run Time Not Updating

- The next scheduled run time is saved to `runs/next_scheduled_run.json`
- It updates each time the scheduler calculates the next window
- If it's not updating, check scheduler logs for errors

## Best Practices

1. **Run as a Service**: Use systemd, launchd, or Windows Service for production deployments
2. **Monitor Logs**: Regularly check logs for errors or warnings
3. **Set Appropriate Schedule**: Choose a time when system load is low
4. **Enable Catch-up**: Set `catch_up_if_missed: true` to handle missed runs automatically
5. **Use Verbose Logging**: Enable `--verbose` during initial setup and troubleshooting
6. **Test First**: Use `simulate-missed` to test catch-up functionality before relying on it

## Related Commands

- **`run-once`**: Run a single transfer manually (useful for testing)
- **`simulate-missed`**: Test catch-up functionality without waiting
- **`status`**: Check current transfer status
- **`monitor`**: Continuously monitor transfer progress
- **`validate`**: Validate configuration before running scheduler

## Additional Resources

- **Main README**: See `README.md` for general usage
- **Installation Guide**: See `INSTALL.md` for service setup
- **Quick Start**: See `QUICKSTART.md` for basic examples
- **Troubleshooting**: See `TROUBLESHOOTING.md` for common issues

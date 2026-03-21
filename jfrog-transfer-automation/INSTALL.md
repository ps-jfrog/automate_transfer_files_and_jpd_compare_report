# Installation Guide

This guide covers installation and running `jfrog-transfer-automation` as a background service on Windows and Linux.

## Prerequisites

### Both Platforms
- **Python 3.9+** - Download from [python.org](https://www.python.org/downloads/)
- **JFrog CLI (`jf`)** - Download from [jfrog.com/getcli/](https://jfrog.com/getcli/)
- **JFrog CLI configured** with source and target server IDs

### Windows
- PowerShell 5.1+ (included with Windows 10/11)
- Administrator access (for Task Scheduler setup)

### Linux
- systemd (most modern distributions)
- sudo/root access (for systemd service setup)

---

## Installation

### Windows

#### Method 1: Using Install Script (Recommended)

1. Open PowerShell (as Administrator if needed)
2. Navigate to the project directory:
   ```powershell
   cd C:\path\to\jfrog-transfer-automation
   ```
3. If you get an execution policy error, run:
   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```
4. Run the install script:
   ```powershell
   .\scripts\install.ps1
   ```

#### Method 2: Manual Installation

1. Open PowerShell or Command Prompt
2. Navigate to the **`jfrog-transfer-automation`** directory (where `pyproject.toml` is located):
   ```powershell
   cd C:\path\to\jfrog-transfer-automation
   ```
   > **Important:** You must run `pip install` from this directory, not the parent
   > repository root. If you see `does not appear to be a Python project`, you are
   > in the wrong directory.
3. (Optional) Create and activate a virtual environment to keep dependencies isolated:
   ```powershell
   python -m venv .venv           # create (one time)
   .venv\Scripts\Activate.ps1     # activate (each new terminal session)
   ```
4. Upgrade pip:
   ```powershell
   python -m pip install --upgrade pip
   ```
5. Install the package:
   ```powershell
   python -m pip install -e .
   ```

### Linux/macOS

#### Method 1: Using Install Script (Recommended)

1. Open a terminal
2. Navigate to the project directory:
   ```bash
   cd /path/to/jfrog-transfer-automation
   ```
3. Make the script executable (if needed):
   ```bash
   chmod +x scripts/install.sh
   ```
4. Run the install script:
   ```bash
   ./scripts/install.sh
   ```

#### Method 2: Manual Installation

1. Open a terminal
2. Navigate to the **`jfrog-transfer-automation`** directory (where `pyproject.toml` is located):
   ```bash
   cd /path/to/jfrog-transfer-automation
   ```
   > **Important:** You must run `pip install` from this directory, not the parent
   > repository root. If you see `does not appear to be a Python project`, you are
   > in the wrong directory.
3. (Optional) Create and activate a virtual environment to keep dependencies isolated:
   ```bash
   python3 -m venv .venv          # create (one time)
   source .venv/bin/activate      # activate (each new terminal session)
   ```
4. Upgrade pip:
   ```bash
   python3 -m pip install --upgrade pip
   ```
5. Install the package:
   ```bash
   python3 -m pip install -e .
   ```

### Updating After Code Changes

The `pip install -e .` command installs the package in **editable mode**, meaning
Python imports directly from your source files on disk. Any code changes you make
are available immediately — no reinstall required.

You only need to re-run `pip install -e .` if you change `pyproject.toml`
(e.g., new dependencies, entry points, or package metadata).

**Verify the install points to your source tree:**
```bash
pip show jfrog-transfer-automation
```

**Reinstall or uninstall if needed:**
```bash
# Reinstall over an existing install (safe to run any time)
pip install -e .

# Full uninstall + reinstall
pip uninstall jfrog-transfer-automation
pip install -e .
```

### Post-Installation

1. **Create configuration file:**
   ```bash
   # Windows
   Copy-Item config.sample.yaml config.yaml
   
   # Linux
   cp config.sample.yaml config.yaml
   ```

2. **Edit `config.yaml`** with your settings:
   - Set `source_server_id` and `target_server_id`
   - Configure schedule times
   - Set repository file path

3. **Validate configuration:**
   ```bash
   jfrog-transfer-automation validate --config config.yaml
   ```

4. **Test with dry run:**
   ```bash
   jfrog-transfer-automation run-once --config config.yaml --dry-run
   ```

---

## Running as a Background Service

### Windows: Using Task Scheduler

#### Option 1: Run Scheduler at Startup

1. **Open Task Scheduler:**
   - Press `Win + R`, type `taskschd.msc`, press Enter
   - Or search "Task Scheduler" in Start menu

2. **Create Basic Task:**
   - Click "Create Basic Task" in the right panel
   - Name: `JFrog Transfer Automation Scheduler`
   - Description: `Runs JFrog transfer automation scheduler daily`

3. **Set Trigger:**
   - Select "When the computer starts"
   - Or select "When I log on" if you want it to run only when you're logged in

4. **Set Action:**
   - Action: "Start a program"
   - Program/script: `python` (or full path: `C:\Python39\python.exe`)
   - Add arguments: `-m jfrog_transfer_automation.cli.main scheduler --config C:\path\to\config.yaml`
   - Start in: `C:\path\to\jfrog-transfer-automation`

5. **Configure Settings:**
   - Check "Run whether user is logged on or not"
   - Check "Run with highest privileges" (if needed)
   - Check "Configure for: Windows 10" (or your OS version)

6. **Finish and Test:**
   - Click Finish
   - Right-click the task → "Run" to test immediately
   - Check "Last Run Result" to verify it started successfully

#### Option 2: Run Scheduler Daily at Specific Time

Follow the same steps as Option 1, but in step 3:
- Select "Daily"
- Set the start time (e.g., 1:00 AM)
- Set recurrence: Every 1 day

**Note:** This approach runs the scheduler command, which then manages its own schedule based on `config.yaml`. The scheduler will sleep until the configured `start_time` and then run transfers according to the schedule.

#### Option 3: Run Transfer Directly (Without Scheduler)

If you prefer Windows Task Scheduler to handle the timing:

1. Create a task that runs daily at your desired time
2. Action: `python -m jfrog_transfer_automation.cli.main run-once --config C:\path\to\config.yaml`
3. This runs a single transfer and exits (no scheduler loop)

#### Viewing Logs on Windows

- Logs are written to: `runs/<timestamp>/run.log`
- Check Task Scheduler history: Task Scheduler → Task Scheduler Library → Your Task → History tab
- For real-time monitoring, use:
  ```powershell
  jfrog-transfer-automation monitor --config config.yaml
  ```

---

### Linux: Using systemd

#### Create systemd Service File

1. **Create service file:**
   ```bash
   sudo nano /etc/systemd/system/jfrog-transfer-automation.service
   ```

2. **Add the following content** (adjust paths as needed):
   ```ini
   [Unit]
   Description=JFrog Transfer Automation Scheduler
   After=network.target

   [Service]
   Type=simple
   User=your-username
   WorkingDirectory=/path/to/jfrog-transfer-automation
   ExecStart=/usr/bin/python3 -m jfrog_transfer_automation.cli.main scheduler --config /path/to/config.yaml
   Restart=always
   RestartSec=10
   StandardOutput=journal
   StandardError=journal

   [Install]
   WantedBy=multi-user.target
   ```

3. **Replace placeholders:**
   - `your-username`: Your Linux username
   - `/path/to/jfrog-transfer-automation`: Full path to project directory
   - `/path/to/config.yaml`: Full path to your config file
   - `/usr/bin/python3`: Path to Python 3 (find with `which python3`)

4. **Reload systemd:**
   ```bash
   sudo systemctl daemon-reload
   ```

5. **Enable service (start on boot):**
   ```bash
   sudo systemctl enable jfrog-transfer-automation.service
   ```

6. **Start service:**
   ```bash
   sudo systemctl start jfrog-transfer-automation.service
   ```

7. **Check status:**
   ```bash
   sudo systemctl status jfrog-transfer-automation.service
   ```

#### Service Management Commands

```bash
# Start service
sudo systemctl start jfrog-transfer-automation.service

# Stop service
sudo systemctl stop jfrog-transfer-automation.service

# Restart service
sudo systemctl restart jfrog-transfer-automation.service

# Check status
sudo systemctl status jfrog-transfer-automation.service

# View logs
sudo journalctl -u jfrog-transfer-automation.service -f

# Disable auto-start on boot
sudo systemctl disable jfrog-transfer-automation.service
```

#### Alternative: Run as User Service (No sudo)

If you don't have root access, you can run as a user service:

1. **Create user systemd directory:**
   ```bash
   mkdir -p ~/.config/systemd/user
   ```

2. **Create service file:**
   ```bash
   nano ~/.config/systemd/user/jfrog-transfer-automation.service
   ```

3. **Use the same content as above** (but remove `User=` line)

4. **Reload and enable:**
   ```bash
   systemctl --user daemon-reload
   systemctl --user enable jfrog-transfer-automation.service
   systemctl --user start jfrog-transfer-automation.service
   ```

5. **Enable lingering** (so service runs even when not logged in):
   ```bash
   loginctl enable-linger $USER
   ```

#### Viewing Logs on Linux

- **systemd logs:**
  ```bash
  sudo journalctl -u jfrog-transfer-automation.service -f
  ```

- **Application logs:**
  - Location: `runs/<timestamp>/run.log`
  - View with: `tail -f runs/*/run.log`

- **Real-time monitoring:**
  ```bash
  jfrog-transfer-automation monitor --config config.yaml
  ```

---

## Alternative: Running in Background Manually

### Windows (PowerShell)

```powershell
# Start in background
Start-Process python -ArgumentList "-m jfrog_transfer_automation.cli.main scheduler --config config.yaml" -WindowStyle Hidden

# Or use the built-in background flag
jfrog-transfer-automation scheduler --config config.yaml --background
```

### Linux (nohup or screen/tmux)

```bash
# Using nohup
nohup jfrog-transfer-automation scheduler --config config.yaml > scheduler.log 2>&1 &

# Using screen
screen -S jfrog-scheduler
jfrog-transfer-automation scheduler --config config.yaml
# Press Ctrl+A then D to detach

# Using tmux
tmux new-session -d -s jfrog-scheduler 'jfrog-transfer-automation scheduler --config config.yaml'
```

---

## Troubleshooting

### Windows

**Issue: "python is not recognized"**
- Solution: Add Python to PATH or use full path to python.exe in Task Scheduler

**Issue: Task runs but immediately stops**
- Check Task Scheduler → History tab for errors
- Verify paths in Task Scheduler action are correct
- Check that config.yaml path is absolute

**Issue: Service doesn't start on boot**
- Verify task is enabled in Task Scheduler
- Check "Run whether user is logged on or not" is selected
- Verify user account has necessary permissions

### Linux

**Issue: Service fails to start**
- Check service status: `sudo systemctl status jfrog-transfer-automation.service`
- View logs: `sudo journalctl -u jfrog-transfer-automation.service -n 50`
- Verify paths in service file are correct and absolute
- Check file permissions on config.yaml

**Issue: Service stops after logout**
- For user services, enable lingering: `loginctl enable-linger $USER`
- For system services, ensure `User=` is set correctly

**Issue: Permission denied**
- Ensure user has read access to config.yaml
- Ensure user has write access to output directory
- Check JFrog CLI permissions

---

## Verification

After setting up the service, verify it's working:

1. **Check service is running:**
   - Windows: Task Scheduler → Your Task → Status
   - Linux: `sudo systemctl status jfrog-transfer-automation.service`

2. **Check for runs:**
   ```bash
   # Check runs directory
   ls -la runs/
   
   # Check latest run
   ls -la runs/*/ | tail -1
   ```

3. **Monitor in real-time:**
   ```bash
   jfrog-transfer-automation monitor --config config.yaml
   ```

4. **Check logs:**
   - Windows: `runs/<timestamp>/run.log`
   - Linux: `sudo journalctl -u jfrog-transfer-automation.service -f`

---

## Next Steps

- Review `QUICKSTART.md` for usage examples
- See `TROUBLESHOOTING.md` for common issues
- Configure notifications in `config.yaml` (email/webhook)
- Test with `--dry-run` before production use

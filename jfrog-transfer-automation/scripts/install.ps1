# Installation script for jfrog-transfer-automation (Windows PowerShell)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

Write-Host "Installing jfrog-transfer-automation..." -ForegroundColor Green

# Check Python
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found: $pythonVersion"
} catch {
    Write-Host "Error: Python not found. Install Python 3.9+ from python.org" -ForegroundColor Red
    exit 1
}

# Check JFrog CLI
try {
    $jfVersion = jf --version 2>&1
    Write-Host "Found: $jfVersion"
} catch {
    Write-Host "Warning: JFrog CLI (jf) not found in PATH" -ForegroundColor Yellow
    Write-Host "Install from: https://jfrog.com/getcli/" -ForegroundColor Yellow
}

# Install package
Set-Location $ProjectDir
python -m pip install --upgrade pip
python -m pip install -e .

Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Copy config.sample.yaml to config.yaml and configure"
Write-Host "2. Run: jfrog-transfer-automation validate --config config.yaml"
Write-Host "3. Run: jfrog-transfer-automation run-once --config config.yaml"

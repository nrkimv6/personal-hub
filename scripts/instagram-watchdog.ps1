# Instagram Worker Watchdog Script
# Monitors the Instagram worker process and automatically restarts it if it crashes
# Usage: .\scripts\instagram-watchdog.ps1

param(
    [int]$CheckInterval = 10,     # Check every 10 seconds
    [int]$MaxRestarts = 5,        # Maximum restarts before giving up
    [int]$RestartWindow = 300     # Reset restart count after this many seconds
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"
$PidDir = Join-Path $ProjectRoot ".pids"
$WorkerPidFile = Join-Path $PidDir "instagram_worker.pid"

# Ensure directories exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

# Restart tracking
$restartCount = 0
$lastRestartTime = Get-Date

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage -ForegroundColor $(
        switch ($Level) {
            "ERROR" { "Red" }
            "WARN"  { "Yellow" }
            "INFO"  { "Cyan" }
            default { "White" }
        }
    )
    # Also log to file
    $logFile = Join-Path $LogDir "instagram_watchdog.log"
    Add-Content -Path $logFile -Value $logMessage -Encoding UTF8
}

function Start-InstagramWorker {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_instagram_$Timestamp.log"

    Write-Log "Starting Instagram worker process..."

    # Use venv python explicitly
    $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }

    Write-Log "Using Python: $VenvPython"

    $workerProcess = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "set PYTHONIOENCODING=utf-8 && `"$VenvPython`" -m app.worker.instagram_worker > `"$stdoutLogFile`" 2>&1" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -PassThru

    # Save PID
    $workerProcess.Id | Out-File $WorkerPidFile -Encoding ascii

    Write-Log "Instagram worker started with PID: $($workerProcess.Id)"
    return $workerProcess.Id
}

function Test-InstagramWorkerRunning {
    if (-not (Test-Path $WorkerPidFile)) {
        return $false
    }

    $savedPid = Get-Content $WorkerPidFile -ErrorAction SilentlyContinue
    if (-not $savedPid) {
        return $false
    }

    $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    return ($null -ne $process)
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Instagram Worker Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

# Initial check
if (-not (Test-InstagramWorkerRunning)) {
    Write-Log "Instagram worker not running, starting..." "WARN"
    Start-InstagramWorker
    $restartCount++
    $lastRestartTime = Get-Date
}

try {
    while ($true) {
        Start-Sleep -Seconds $CheckInterval

        # Reset restart count if enough time has passed
        $timeSinceLastRestart = ((Get-Date) - $lastRestartTime).TotalSeconds
        if ($timeSinceLastRestart -gt $RestartWindow) {
            if ($restartCount -gt 0) {
                Write-Log "Restart count reset (no crashes in ${RestartWindow}s)"
                $restartCount = 0
            }
        }

        # Check if worker is running
        if (-not (Test-InstagramWorkerRunning)) {
            Write-Log "Instagram worker process died!" "ERROR"

            # Check restart limit
            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Please check the Instagram worker logs for the root cause." "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            # Restart
            Write-Log "Restarting Instagram worker (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-InstagramWorker
            $restartCount++
            $lastRestartTime = Get-Date
        }
    }
}
catch {
    Write-Log "Instagram Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Instagram Watchdog stopped"
}

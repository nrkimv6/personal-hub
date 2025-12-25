# Monitor Worker Watchdog Script
# Monitors the worker process and automatically restarts it if it crashes
# Usage: .\scripts\worker-watchdog.ps1

param(
    [int]$CheckInterval = 10,     # Check every 10 seconds
    [int]$MaxRestarts = 5,        # Maximum restarts before giving up
    [int]$RestartWindow = 300     # Reset restart count after this many seconds
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Use APP_MODE environment variable to determine log directory
$isDev = $env:APP_MODE -eq "development"
if ($isDev) {
    $LogDir = Join-Path $ProjectRoot "logs\dev"
    $PidSuffix = "_dev"
} else {
    $LogDir = Join-Path $ProjectRoot "logs"
    $PidSuffix = ""
}
$PidDir = Join-Path $ProjectRoot ".pids"
$WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"

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
    $logFile = Join-Path $LogDir "watchdog.log"
    Add-Content -Path $logFile -Value $logMessage -Encoding UTF8
}

function Start-WorkerProcess {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_worker_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_worker_$Timestamp.log"

    Write-Log "Starting worker process..."

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

    # Set environment variables
    $env:PYTHONIOENCODING = "utf-8"
    $env:APP_MODE = if ($isDev) { "development" } else { "production" }

    # Start python directly (NOT via cmd.exe) to get correct PID
    $workerProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "app.worker.monitor_worker" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # Save PID - this is now the actual python process PID
    $workerProcess.Id | Out-File $WorkerPidFile -Encoding ascii

    Write-Log "Worker started with PID: $($workerProcess.Id)"
    return $workerProcess.Id
}

function Test-WorkerRunning {
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

# Kill any orphaned worker processes before starting
function Stop-OrphanedWorkers {
    Write-Log "Checking for orphaned monitor worker processes..."
    $killedCount = 0

    # Find all python processes running monitor_worker
    $pythonProcs = Get-Process -Name "python*" -ErrorAction SilentlyContinue
    foreach ($proc in $pythonProcs) {
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdLine -and $cmdLine -like "*app.worker.monitor_worker*") {
                # Check if this is our managed worker
                $savedPid = if (Test-Path $WorkerPidFile) { Get-Content $WorkerPidFile -ErrorAction SilentlyContinue } else { $null }
                if ($proc.Id -ne $savedPid) {
                    Write-Log "Killing orphaned monitor worker (PID: $($proc.Id))" "WARN"
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                    $killedCount++
                }
            }
        } catch {
            # Ignore errors
        }
    }

    if ($killedCount -gt 0) {
        Write-Log "Killed $killedCount orphaned monitor worker(s)"
        Start-Sleep -Seconds 2  # Wait for processes to fully terminate
    }
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Worker Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

# Kill orphaned workers before starting
Stop-OrphanedWorkers

# Initial check
if (-not (Test-WorkerRunning)) {
    Write-Log "Worker not running, starting..." "WARN"
    Start-WorkerProcess
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
        if (-not (Test-WorkerRunning)) {
            Write-Log "Worker process died!" "ERROR"

            # Check restart limit
            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Please check the worker logs for the root cause." "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            # Restart
            Write-Log "Restarting worker (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-WorkerProcess
            $restartCount++
            $lastRestartTime = Get-Date
        }
    }
}
catch {
    Write-Log "Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Watchdog stopped"
}

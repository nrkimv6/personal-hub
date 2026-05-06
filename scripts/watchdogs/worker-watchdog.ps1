param(
    [int]$CheckInterval = 10,
    [int]$MaxRestarts = 5,
    [int]$RestartWindow = 300
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

. (Join-Path $ScriptDir "watchdog-utils.ps1")

$paths = Get-WatchdogPaths -ProjectRoot $ProjectRoot
$LogDir = $paths.LogDir
$PidDir = $paths.PidDir
$PidSuffix = $paths.PidSuffix
$isAdmin = $paths.IsAdmin
$WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"

$script:watchdogLogFile = Join-Path $LogDir "watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Start-LegacyWorker {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_worker_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_worker_$Timestamp.log"

    Write-Log "Starting worker process..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    Write-Log "Using Python: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "worker" `
        -Python $VenvPython `
        -ArgList @("-m", "app.worker.monitor_worker") `
        -WorkingDir $ProjectRoot `
        -StdoutLog $stdoutLogFile `
        -StderrLog $stderrLogFile `
        -NamePattern 'python' `
        -CmdlinePattern 'app\.worker\.monitor_worker' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8"; APP_MODE = $(if ($isAdmin) { "admin" } else { "public" }) }

    Write-Log "Worker started with PID: $actualPid"
    return $actualPid
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Worker Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "Worker" `
    -StartTarget { Start-LegacyWorker } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow

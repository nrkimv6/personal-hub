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
$WorkerPidFile = Join-Path $PidDir "unified_worker$PidSuffix.pid"

$script:watchdogLogFile = Join-Path $LogDir "unified_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Start-UnifiedWorker {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_unified_worker_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_unified_worker_$Timestamp.log"

    Write-Log "Starting unified worker process (all workers via WorkerOrchestrator)..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot -AliasName "monitorpage-worker.exe"
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    Write-Log "Using Python: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "unified worker" `
        -Python $VenvPython `
        -ArgList @("-m", "app.worker.main") `
        -WorkingDir $ProjectRoot `
        -StdoutLog $stdoutLogFile `
        -StderrLog $stderrLogFile `
        -NamePattern 'monitorpage-worker|python' `
        -CmdlinePattern 'app\.worker\.main' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8"; APP_MODE = $(if ($isAdmin) { "admin" } else { "public" }) } `
        -RegisterRole "worker" `
        -RegisterName "unified-worker" `
        -ParentPid $PID

    Write-Log "Unified worker started with PID: $actualPid"
    Write-Log "  -> NaverMonitorWorker"
    Write-Log "  -> ScheduledCrawlWorker"
    Write-Log "  -> OnDemandCrawlWorker"
    return $actualPid
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Unified Worker Watchdog Started"
Write-Log "(WorkerOrchestrator Architecture)"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "Unified worker" `
    -StartTarget { Start-UnifiedWorker } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow

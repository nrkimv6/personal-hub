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
$WorkerPidFile = Join-Path $PidDir "crawl_worker$PidSuffix.pid"

$script:watchdogLogFile = Join-Path $LogDir "crawl_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Start-CrawlWorker {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_crawl_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_crawl_$Timestamp.log"

    Write-Log "Starting Crawl worker process (Instagram + Universal)..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    Write-Log "Using Python: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "crawl worker" `
        -Python $VenvPython `
        -ArgList @("-m", "app.worker.main") `
        -WorkingDir $ProjectRoot `
        -StdoutLog $stdoutLogFile `
        -StderrLog $stderrLogFile `
        -NamePattern 'python' `
        -CmdlinePattern 'app\.worker\.main' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8"; APP_MODE = $(if ($isAdmin) { "admin" } else { "public" }) }

    Write-Log "Crawl worker started with PID: $actualPid"
    return $actualPid
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Crawl Worker Watchdog Started (Instagram + Universal)"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "Crawl worker" `
    -StartTarget { Start-CrawlWorker } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow

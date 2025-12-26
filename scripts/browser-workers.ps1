# Browser Workers Management Script
# Manages browser-based workers (monitor_worker, instagram_worker) for user session execution
#
# Usage:
#   .\scripts\browser-workers.ps1 -Action start    # Start browser workers
#   .\scripts\browser-workers.ps1 -Action stop     # Stop browser workers
#   .\scripts\browser-workers.ps1 -Action restart  # Restart browser workers
#   .\scripts\browser-workers.ps1 -Action status   # Show status
#
# Note: This script is for Dev mode only (browser workers require user session)

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop", "restart", "status")]
    [string]$Action
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Dev mode only - browser workers need user session
$env:APP_MODE = "development"
$LogDir = Join-Path $ProjectRoot "logs\dev"
$PidDir = Join-Path $ProjectRoot ".pids"
$PidSuffix = "_dev"

# Ensure directories exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

# PID files for browser workers
$WatchdogPidFile = Join-Path $PidDir "watchdog$PidSuffix.pid"
$InstagramWatchdogPidFile = Join-Path $PidDir "instagram_watchdog$PidSuffix.pid"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN"  { "Yellow" }
        "INFO"  { "Cyan" }
        "OK"    { "Green" }
        default { "White" }
    }
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

function Test-ProcessRunning {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if (-not $savedPid) {
        return $false
    }

    $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    return $null -ne $proc
}

function Start-BrowserWorkers {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Starting Browser Workers" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    $started = 0

    # Start Monitor Worker Watchdog
    if (Test-ProcessRunning $WatchdogPidFile) {
        Write-Log "Monitor Worker Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Monitor Worker Watchdog..."
        $watchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\worker-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $watchdogProcess.Id | Out-File $WatchdogPidFile -Encoding ascii
        Write-Log "Monitor Worker Watchdog started (PID: $($watchdogProcess.Id))" "OK"
        $started++
    }

    # Start Instagram Worker Watchdog
    if (Test-ProcessRunning $InstagramWatchdogPidFile) {
        Write-Log "Instagram Worker Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Instagram Worker Watchdog..."
        $igWatchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\instagram-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $igWatchdogProcess.Id | Out-File $InstagramWatchdogPidFile -Encoding ascii
        Write-Log "Instagram Worker Watchdog started (PID: $($igWatchdogProcess.Id))" "OK"
        $started++
    }

    if ($started -gt 0) {
        Write-Host ""
        Write-Log "$started browser worker(s) started" "OK"
    } else {
        Write-Host ""
        Write-Log "All browser workers already running" "WARN"
    }
}

function Stop-BrowserWorkers {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  Stopping Browser Workers" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""

    $stopped = 0

    # Stop Monitor Worker Watchdog
    if (Test-Path $WatchdogPidFile) {
        $savedPid = Get-Content $WatchdogPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Stopping Monitor Worker Watchdog (PID: $savedPid)..."
                Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                Write-Log "Monitor Worker Watchdog stopped" "OK"
                $stopped++
            }
        }
        Remove-Item $WatchdogPidFile -Force -ErrorAction SilentlyContinue
    }

    # Stop Instagram Worker Watchdog
    if (Test-Path $InstagramWatchdogPidFile) {
        $savedPid = Get-Content $InstagramWatchdogPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Stopping Instagram Worker Watchdog (PID: $savedPid)..."
                Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                Write-Log "Instagram Worker Watchdog stopped" "OK"
                $stopped++
            }
        }
        Remove-Item $InstagramWatchdogPidFile -Force -ErrorAction SilentlyContinue
    }

    # Also stop the actual worker processes (they may linger after watchdog stops)
    $WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"
    $InstagramWorkerPidFile = Join-Path $PidDir "instagram_worker$PidSuffix.pid"

    foreach ($pidFile in @($WorkerPidFile, $InstagramWorkerPidFile)) {
        if (Test-Path $pidFile) {
            $savedPid = Get-Content $pidFile -ErrorAction SilentlyContinue
            if ($savedPid) {
                $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Log "Stopping worker process (PID: $savedPid)..."
                    Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        }
    }

    if ($stopped -gt 0) {
        Write-Host ""
        Write-Log "$stopped browser worker(s) stopped" "OK"
    } else {
        Write-Host ""
        Write-Log "No browser workers were running" "WARN"
    }
}

function Show-Status {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Browser Workers Status" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Monitor Worker Watchdog
    Write-Host "Monitor Worker Watchdog:" -ForegroundColor White
    if (Test-ProcessRunning $WatchdogPidFile) {
        $savedPid = Get-Content $WatchdogPidFile
        Write-Host "  [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "  [-] Not running" -ForegroundColor Yellow
    }

    # Instagram Worker Watchdog
    Write-Host "Instagram Worker Watchdog:" -ForegroundColor White
    if (Test-ProcessRunning $InstagramWatchdogPidFile) {
        $savedPid = Get-Content $InstagramWatchdogPidFile
        Write-Host "  [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "  [-] Not running" -ForegroundColor Yellow
    }

    # Actual worker processes
    $WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"
    $InstagramWorkerPidFile = Join-Path $PidDir "instagram_worker$PidSuffix.pid"

    Write-Host ""
    Write-Host "Worker Processes:" -ForegroundColor White

    Write-Host "  Monitor Worker:" -ForegroundColor Gray
    if (Test-ProcessRunning $WorkerPidFile) {
        $savedPid = Get-Content $WorkerPidFile
        Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "    [-] Not running" -ForegroundColor Yellow
    }

    Write-Host "  Instagram Worker:" -ForegroundColor Gray
    if (Test-ProcessRunning $InstagramWorkerPidFile) {
        $savedPid = Get-Content $InstagramWorkerPidFile
        Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "    [-] Not running" -ForegroundColor Yellow
    }

    Write-Host ""
}

# Main execution
switch ($Action) {
    "start" {
        Start-BrowserWorkers
    }
    "stop" {
        Stop-BrowserWorkers
    }
    "restart" {
        Stop-BrowserWorkers
        Start-Sleep -Seconds 2
        Start-BrowserWorkers
    }
    "status" {
        Show-Status
    }
}

Write-Host ""

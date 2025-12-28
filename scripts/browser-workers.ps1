# Browser Workers Management Script
# Manages browser-based workers (monitor_worker, crawl_worker) for user session execution
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
$CrawlWatchdogPidFile = Join-Path $PidDir "crawl_watchdog$PidSuffix.pid"
$ClaudeWatchdogPidFile = Join-Path $PidDir "claude_watchdog$PidSuffix.pid"

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
        # Set APP_MODE environment variable for child process
        $env:APP_MODE = "development"
        $watchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\worker-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $watchdogProcess.Id | Out-File $WatchdogPidFile -Encoding ascii
        Write-Log "Monitor Worker Watchdog started (PID: $($watchdogProcess.Id))" "OK"
        $started++
    }

    # Start Crawl Worker Watchdog (Instagram + Universal)
    if (Test-ProcessRunning $CrawlWatchdogPidFile) {
        Write-Log "Crawl Worker Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Crawl Worker Watchdog..."
        # Set APP_MODE environment variable for child process
        $env:APP_MODE = "development"
        $crawlWatchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\crawl-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $crawlWatchdogProcess.Id | Out-File $CrawlWatchdogPidFile -Encoding ascii
        Write-Log "Crawl Worker Watchdog started (PID: $($crawlWatchdogProcess.Id))" "OK"
        $started++
    }

    # Start Claude Worker Watchdog
    if (Test-ProcessRunning $ClaudeWatchdogPidFile) {
        Write-Log "Claude Worker Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Claude Worker Watchdog..."
        # Set APP_MODE environment variable for child process
        $env:APP_MODE = "development"
        $claudeWatchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\claude-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $claudeWatchdogProcess.Id | Out-File $ClaudeWatchdogPidFile -Encoding ascii
        Write-Log "Claude Worker Watchdog started (PID: $($claudeWatchdogProcess.Id))" "OK"
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

    # Stop Crawl Worker Watchdog
    if (Test-Path $CrawlWatchdogPidFile) {
        $savedPid = Get-Content $CrawlWatchdogPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Stopping Crawl Worker Watchdog (PID: $savedPid)..."
                Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                Write-Log "Crawl Worker Watchdog stopped" "OK"
                $stopped++
            }
        }
        Remove-Item $CrawlWatchdogPidFile -Force -ErrorAction SilentlyContinue
    }

    # Stop Claude Worker Watchdog
    if (Test-Path $ClaudeWatchdogPidFile) {
        $savedPid = Get-Content $ClaudeWatchdogPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Stopping Claude Worker Watchdog (PID: $savedPid)..."
                Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                Write-Log "Claude Worker Watchdog stopped" "OK"
                $stopped++
            }
        }
        Remove-Item $ClaudeWatchdogPidFile -Force -ErrorAction SilentlyContinue
    }

    # Also stop the actual worker processes (they may linger after watchdog stops)
    $WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"
    $CrawlWorkerPidFile = Join-Path $PidDir "crawl_worker$PidSuffix.pid"
    $ClaudeWorkerPidFile = Join-Path $PidDir "llm_worker$PidSuffix.pid"

    foreach ($pidFile in @($WorkerPidFile, $CrawlWorkerPidFile, $ClaudeWorkerPidFile)) {
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

    # Crawl Worker Watchdog
    Write-Host "Crawl Worker Watchdog:" -ForegroundColor White
    if (Test-ProcessRunning $CrawlWatchdogPidFile) {
        $savedPid = Get-Content $CrawlWatchdogPidFile
        Write-Host "  [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "  [-] Not running" -ForegroundColor Yellow
    }

    # Claude Worker Watchdog
    Write-Host "Claude Worker Watchdog:" -ForegroundColor White
    if (Test-ProcessRunning $ClaudeWatchdogPidFile) {
        $savedPid = Get-Content $ClaudeWatchdogPidFile
        Write-Host "  [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "  [-] Not running" -ForegroundColor Yellow
    }

    # Actual worker processes
    $WorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"
    $CrawlWorkerPidFile = Join-Path $PidDir "crawl_worker$PidSuffix.pid"
    $ClaudeWorkerPidFile = Join-Path $PidDir "llm_worker$PidSuffix.pid"

    Write-Host ""
    Write-Host "Worker Processes:" -ForegroundColor White

    Write-Host "  Monitor Worker:" -ForegroundColor Gray
    if (Test-ProcessRunning $WorkerPidFile) {
        $savedPid = Get-Content $WorkerPidFile
        Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "    [-] Not running" -ForegroundColor Yellow
    }

    Write-Host "  Crawl Worker:" -ForegroundColor Gray
    if (Test-ProcessRunning $CrawlWorkerPidFile) {
        $savedPid = Get-Content $CrawlWorkerPidFile
        Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "    [-] Not running" -ForegroundColor Yellow
    }

    Write-Host "  Claude Worker:" -ForegroundColor Gray
    if (Test-ProcessRunning $ClaudeWorkerPidFile) {
        $savedPid = Get-Content $ClaudeWorkerPidFile
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

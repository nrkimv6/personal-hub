# Browser Workers Management Script
# Manages browser-based workers via WorkerOrchestrator for user session execution
#
# Usage:
#   .\scripts\browser-workers.ps1 -Action start       # Start browser workers
#   .\scripts\browser-workers.ps1 -Action stop        # Stop browser workers
#   .\scripts\browser-workers.ps1 -Action restart     # Restart browser workers
#   .\scripts\browser-workers.ps1 -Action status      # Show status
#   .\scripts\browser-workers.ps1 -Action restart-api # Restart API server (NSSM service)
#
# Note: This script is for Dev mode only (browser workers require user session)
#
# Architecture:
#   - All workers (Naver, Instagram, Universal) run via WorkerOrchestrator
#   - Single entry point: app.worker.main
#   - Claude worker runs separately

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("start", "stop", "restart", "status", "restart-api")]
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

# PID files - unified worker watchdog + Claude + Video Download
$WorkerWatchdogPidFile = Join-Path $PidDir "worker_watchdog$PidSuffix.pid"
$ClaudeWatchdogPidFile = Join-Path $PidDir "claude_watchdog$PidSuffix.pid"
$VideoDownloadWatchdogPidFile = Join-Path $PidDir "video_download_watchdog$PidSuffix.pid"

# Legacy PID files (for cleanup)
$LegacyWatchdogPidFile = Join-Path $PidDir "watchdog$PidSuffix.pid"
$LegacyCrawlWatchdogPidFile = Join-Path $PidDir "crawl_watchdog$PidSuffix.pid"

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

function Stop-LegacyWatchdogs {
    # Clean up legacy watchdog processes (old monitor_worker + crawl_worker separate watchdogs)
    foreach ($legacyPidFile in @($LegacyWatchdogPidFile, $LegacyCrawlWatchdogPidFile)) {
        if (Test-Path $legacyPidFile) {
            $savedPid = Get-Content $legacyPidFile -ErrorAction SilentlyContinue
            if ($savedPid) {
                $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Log "Stopping legacy watchdog (PID: $savedPid)..." "WARN"
                    Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $legacyPidFile -Force -ErrorAction SilentlyContinue
        }
    }

    # Stop legacy worker processes
    $LegacyWorkerPidFile = Join-Path $PidDir "worker$PidSuffix.pid"
    $LegacyCrawlWorkerPidFile = Join-Path $PidDir "crawl_worker$PidSuffix.pid"

    foreach ($legacyPidFile in @($LegacyWorkerPidFile, $LegacyCrawlWorkerPidFile)) {
        if (Test-Path $legacyPidFile) {
            $savedPid = Get-Content $legacyPidFile -ErrorAction SilentlyContinue
            if ($savedPid) {
                $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Log "Stopping legacy worker (PID: $savedPid)..." "WARN"
                    Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $legacyPidFile -Force -ErrorAction SilentlyContinue
        }
    }
}

function Start-BrowserWorkers {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Starting Browser Workers" -ForegroundColor Cyan
    Write-Host "  (WorkerOrchestrator Architecture)" -ForegroundColor Gray
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # First, clean up any legacy processes
    Stop-LegacyWatchdogs

    $started = 0

    # Start Unified Worker Watchdog (Naver + Instagram + Universal via WorkerOrchestrator)
    if (Test-ProcessRunning $WorkerWatchdogPidFile) {
        Write-Log "Worker Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Worker Watchdog (all workers via WorkerOrchestrator)..."
        $env:APP_MODE = "development"
        $watchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\unified-worker-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $watchdogProcess.Id | Out-File $WorkerWatchdogPidFile -Encoding ascii
        Write-Log "Worker Watchdog started (PID: $($watchdogProcess.Id))" "OK"
        $started++
    }

    # Start Claude Worker Watchdog (separate process)
    if (Test-ProcessRunning $ClaudeWatchdogPidFile) {
        Write-Log "Claude Worker Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Claude Worker Watchdog..."
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

    # Start Video Download Worker Watchdog (separate process, no browser needed)
    if (Test-ProcessRunning $VideoDownloadWatchdogPidFile) {
        Write-Log "Video Download Watchdog already running" "WARN"
    } else {
        Write-Log "Starting Video Download Watchdog..."
        $env:APP_MODE = "development"
        $videoDownloadWatchdogProcess = Start-Process -FilePath "powershell.exe" `
            -ArgumentList "-ExecutionPolicy", "Bypass", "-File", "$ScriptDir\video-download-watchdog.ps1" `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Hidden `
            -PassThru
        $videoDownloadWatchdogProcess.Id | Out-File $VideoDownloadWatchdogPidFile -Encoding ascii
        Write-Log "Video Download Watchdog started (PID: $($videoDownloadWatchdogProcess.Id))" "OK"
        $started++
    }

    if ($started -gt 0) {
        Write-Host ""
        Write-Log "$started watchdog(s) started" "OK"
    } else {
        Write-Host ""
        Write-Log "All watchdogs already running" "WARN"
    }
}

function Stop-BrowserWorkers {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  Stopping Browser Workers" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""

    $stopped = 0

    # Stop Worker Watchdog (unified)
    if (Test-Path $WorkerWatchdogPidFile) {
        $savedPid = Get-Content $WorkerWatchdogPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Stopping Worker Watchdog (PID: $savedPid)..."
                Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                Write-Log "Worker Watchdog stopped" "OK"
                $stopped++
            }
        }
        Remove-Item $WorkerWatchdogPidFile -Force -ErrorAction SilentlyContinue
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

    # Stop Video Download Worker Watchdog
    if (Test-Path $VideoDownloadWatchdogPidFile) {
        $savedPid = Get-Content $VideoDownloadWatchdogPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Log "Stopping Video Download Watchdog (PID: $savedPid)..."
                Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                Write-Log "Video Download Watchdog stopped" "OK"
                $stopped++
            }
        }
        Remove-Item $VideoDownloadWatchdogPidFile -Force -ErrorAction SilentlyContinue
    }

    # Stop actual worker processes
    $UnifiedWorkerPidFile = Join-Path $PidDir "unified_worker$PidSuffix.pid"
    $ClaudeWorkerPidFile = Join-Path $PidDir "claude_worker$PidSuffix.pid"
    $VideoDownloadWorkerPidFile = Join-Path $PidDir "video_download_worker$PidSuffix.pid"

    foreach ($pidFile in @($UnifiedWorkerPidFile, $ClaudeWorkerPidFile, $VideoDownloadWorkerPidFile)) {
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

    # Also clean up legacy processes
    Stop-LegacyWatchdogs

    if ($stopped -gt 0) {
        Write-Host ""
        Write-Log "$stopped watchdog(s) stopped" "OK"
    } else {
        Write-Host ""
        Write-Log "No watchdogs were running" "WARN"
    }
}

function Restart-ApiServer {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host "  Restarting API Server" -ForegroundColor Yellow
    Write-Host "  (Hot reload disabled - manual restart)" -ForegroundColor Gray
    Write-Host "========================================" -ForegroundColor Yellow
    Write-Host ""

    $serviceName = "Monitor Page (Development)"
    $apiPidFile = Join-Path $PidDir "api$PidSuffix.pid"

    # Check if running as admin
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    if ($isAdmin) {
        # Admin: use NSSM restart
        Write-Log "Restarting NSSM service: $serviceName"
        try {
            $result = nssm restart $serviceName 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Log "API server restarted successfully" "OK"
            } else {
                Write-Log "NSSM restart failed: $result" "ERROR"
            }
        } catch {
            Write-Log "Failed to restart NSSM service: $_" "ERROR"
        }
    } else {
        # Non-admin: kill process, NSSM will auto-restart
        Write-Log "Non-admin mode: killing API process (NSSM will auto-restart)"

        if (Test-Path $apiPidFile) {
            $savedPid = Get-Content $apiPidFile -ErrorAction SilentlyContinue
            if ($savedPid) {
                $proc = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
                if ($proc) {
                    Write-Log "Stopping API process (PID: $savedPid)..."
                    Stop-Process -Id $savedPid -Force -ErrorAction SilentlyContinue
                    Write-Log "API process stopped. NSSM will auto-restart." "OK"
                } else {
                    Write-Log "API process not found (PID: $savedPid)" "WARN"
                }
            }
        } else {
            # Try to find by port
            Write-Log "PID file not found, trying to find by port 8001..."
            $conn = Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
            if ($conn) {
                $procId = $conn.OwningProcess
                Write-Log "Found process on port 8001 (PID: $procId), stopping..."
                Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
                Write-Log "API process stopped. NSSM will auto-restart." "OK"
            } else {
                Write-Log "No process found on port 8001" "WARN"
            }
        }
    }

    # Wait and check
    Write-Log "Waiting for API to restart..."
    Start-Sleep -Seconds 5

    try {
        $response = Invoke-WebRequest "http://localhost:8001/api/v1/system/status" -TimeoutSec 5 -UseBasicParsing
        if ($response.StatusCode -eq 200) {
            Write-Log "API server is healthy" "OK"
        }
    } catch {
        Write-Log "API not responding yet (may still be starting)" "WARN"
    }
}

function Show-Status {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Browser Workers Status" -ForegroundColor Cyan
    Write-Host "  (WorkerOrchestrator Architecture)" -ForegroundColor Gray
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Unified Worker Watchdog
    Write-Host "Worker Watchdog (Naver + Instagram + Universal):" -ForegroundColor White
    if (Test-ProcessRunning $WorkerWatchdogPidFile) {
        $savedPid = Get-Content $WorkerWatchdogPidFile
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

    # Video Download Worker Watchdog
    Write-Host "Video Download Watchdog:" -ForegroundColor White
    if (Test-ProcessRunning $VideoDownloadWatchdogPidFile) {
        $savedPid = Get-Content $VideoDownloadWatchdogPidFile
        Write-Host "  [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "  [-] Not running" -ForegroundColor Yellow
    }

    # Actual worker processes
    $UnifiedWorkerPidFile = Join-Path $PidDir "unified_worker$PidSuffix.pid"
    $ClaudeWorkerPidFile = Join-Path $PidDir "claude_worker$PidSuffix.pid"
    $VideoDownloadWorkerPidFile = Join-Path $PidDir "video_download_worker$PidSuffix.pid"

    Write-Host ""
    Write-Host "Worker Processes:" -ForegroundColor White

    Write-Host "  Unified Worker (via Orchestrator):" -ForegroundColor Gray
    if (Test-ProcessRunning $UnifiedWorkerPidFile) {
        $savedPid = Get-Content $UnifiedWorkerPidFile
        Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
        Write-Host "        -> NaverMonitorWorker" -ForegroundColor DarkGray
        Write-Host "        -> ScheduledCrawlWorker" -ForegroundColor DarkGray
        Write-Host "        -> OnDemandCrawlWorker" -ForegroundColor DarkGray
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

    Write-Host "  Video Download Worker:" -ForegroundColor Gray
    if (Test-ProcessRunning $VideoDownloadWorkerPidFile) {
        $savedPid = Get-Content $VideoDownloadWorkerPidFile
        Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
    } else {
        Write-Host "    [-] Not running" -ForegroundColor Yellow
    }

    # Check for legacy processes
    $hasLegacy = $false
    foreach ($legacyFile in @($LegacyWatchdogPidFile, $LegacyCrawlWatchdogPidFile)) {
        if (Test-ProcessRunning $legacyFile) {
            $hasLegacy = $true
            break
        }
    }

    if ($hasLegacy) {
        Write-Host ""
        Write-Host "Legacy Processes (should be cleaned up):" -ForegroundColor Yellow
        if (Test-ProcessRunning $LegacyWatchdogPidFile) {
            $savedPid = Get-Content $LegacyWatchdogPidFile
            Write-Host "  [!] Legacy Monitor Watchdog (PID: $savedPid)" -ForegroundColor Yellow
        }
        if (Test-ProcessRunning $LegacyCrawlWatchdogPidFile) {
            $savedPid = Get-Content $LegacyCrawlWatchdogPidFile
            Write-Host "  [!] Legacy Crawl Watchdog (PID: $savedPid)" -ForegroundColor Yellow
        }
        Write-Host ""
        Write-Host "Run 'browser-workers.ps1 -Action restart' to clean up legacy processes" -ForegroundColor DarkYellow
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
    "restart-api" {
        Restart-ApiServer
    }
    "status" {
        Show-Status
    }
}

Write-Host ""

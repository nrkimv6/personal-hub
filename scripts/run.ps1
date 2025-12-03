# Monitor Page - Integrated Run Script
# Starts all processes, shows logs, and stops on exit (Ctrl+C)

param(
    [switch]$Dev  # Pass -Dev to start.ps1 for frontend foreground mode
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page - Integrated Runner" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Start all processes (API, Worker, Frontend)"
Write-Host "  2. Show real-time logs"
Write-Host "  3. Stop all processes when you press Ctrl+C"
Write-Host ""

# Register cleanup on script exit
$stopScript = Join-Path $ScriptDir "stop.ps1"

# Use Register-EngineEvent for Ctrl+C handling
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Write-Host "`n`n[!] Shutting down..." -ForegroundColor Yellow
}

try {
    # Step 1: Start processes
    Write-Host "[Step 1] Starting processes..." -ForegroundColor Cyan
    Write-Host "----------------------------------------"

    $startScript = Join-Path $ScriptDir "start.ps1"

    if ($Dev) {
        # In Dev mode, frontend runs in foreground
        # When user exits frontend (Ctrl+C), we'll stop everything
        Write-Host "[!] Dev mode: Frontend will run in foreground" -ForegroundColor Yellow
        Write-Host ""
        & $startScript -Dev
    } else {
        # Normal mode: all background, then follow logs
        & $startScript

        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
            Write-Host "[!] Start script returned non-zero exit code" -ForegroundColor Yellow
        }

        # Step 2: Show logs (in follow mode)
        Write-Host ""
        Write-Host "[Step 2] Following logs (Ctrl+C to stop)..." -ForegroundColor Cyan
        Write-Host "----------------------------------------"

        $logsScript = Join-Path $ScriptDir "logs.ps1"
        & $logsScript -Follow
    }

} finally {
    # Step 3: Stop all processes on exit
    Write-Host ""
    Write-Host ""
    Write-Host "[Step 3] Stopping all processes..." -ForegroundColor Yellow
    Write-Host "----------------------------------------"

    & $stopScript -Force

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Run complete" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
}

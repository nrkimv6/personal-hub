# Startup wrapper for frontend memory-aware watchdog.

param(
    [int]$Delay = 30
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$WatchdogScript = Join-Path $ScriptDir "frontend-watchdog.ps1"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $ProjectRoot "logs\admin\startup_frontend_watchdog_$timestamp.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    $logDir = Split-Path -Parent $LogFile
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

Write-Log "Startup frontend watchdog script started"
Write-Log "Waiting ${Delay}s before watchdog launch"
Start-Sleep -Seconds $Delay

$pidFile = Join-Path $ProjectRoot ".pids\frontend_watchdog_admin.pid"
$pidDir = Split-Path -Parent $pidFile
if (-not (Test-Path $pidDir)) {
    New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
}
$PID | Out-File $pidFile -Encoding ascii
Write-Log "Supervisor PID ($PID) saved to $pidFile"

$restartCount = 0
while ($true) {
    $restartCount++
    Write-Log "Starting frontend-watchdog.ps1 (attempt #$restartCount)..."
    try {
        & $WatchdogScript
    } catch {
        Write-Log "ERROR: frontend-watchdog.ps1 crashed: $($_.Exception.Message)"
    }
    Write-Log "WARNING: frontend-watchdog.ps1 exited unexpectedly. Restarting in 5 seconds..."
    Start-Sleep -Seconds 5
}

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
$WorkerPidFile = Join-Path $PidDir "claude_worker$PidSuffix.pid"
$script:watchdogLogFile = Join-Path $LogDir "claude_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Start-ClaudeWorker {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stderrLogFile = Join-Path $LogDir "stderr_llm_worker_$Timestamp.log"

    Write-Log "Starting Claude worker process..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot -AliasName "monitorpage-claude.exe"
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    Write-Log "Using Python: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "claude worker" `
        -Python $VenvPython `
        -ArgList @("-m", "app.modules.claude_worker.worker.worker") `
        -WorkingDir $ProjectRoot `
        -StderrLog $stderrLogFile `
        -NamePattern 'monitorpage-claude|python' `
        -CmdlinePattern 'claude_worker\.worker\.worker' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8"; APP_MODE = $(if ($isAdmin) { "admin" } else { "public" }) } `
        -RegisterRole "claude" `
        -RegisterName "claude-worker" `
        -ParentPid $PID

    Write-Log "Claude worker started with PID: $actualPid"
    return $actualPid
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Claude Worker Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "Claude worker" `
    -StartTarget { Start-ClaudeWorker } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow

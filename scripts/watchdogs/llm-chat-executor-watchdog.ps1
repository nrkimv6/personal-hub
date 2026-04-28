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
$isAdmin = $paths.IsAdmin
$WorkerPidFile = Join-Path $PidDir "chat_executor_admin.pid"
$WatchdogPidFile = Join-Path $PidDir "chat_executor_watchdog_admin.pid"

$PID | Out-File $WatchdogPidFile -Encoding ascii

$script:watchdogLogFile = Join-Path $LogDir "chat_executor_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Start-ChatExecutor {
    if (Test-Path $WorkerPidFile) {
        Remove-Item -Force -ErrorAction SilentlyContinue $WorkerPidFile
        Write-Log "Removed stale PID file before launch"
    }

    $stderrLogFile = Join-Path $LogDir "chat_executor_stderr.log"

    Write-Log "Starting Chat Executor process..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot -AliasName "monitorpage-chat.exe"
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    Write-Log "Using Python: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "chat executor" `
        -Python $VenvPython `
        -ArgList @("-m", "app.modules.claude_worker.worker.chat_executor") `
        -WorkingDir $ProjectRoot `
        -StderrLog $stderrLogFile `
        -NamePattern 'monitorpage-chat|python' `
        -CmdlinePattern 'claude_worker\.worker\.chat_executor' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8"; APP_MODE = $(if ($isAdmin) { "admin" } else { "public" }) }

    Write-Log "Chat Executor started with PID: $actualPid"
    return $actualPid
}

# Main watchdog loop
Write-Log ("=" * 50)
Write-Log "Chat Executor Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "Chat Executor" `
    -StartTarget { Start-ChatExecutor } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow `
    -OnExit {
        if (Test-Path $WatchdogPidFile) {
            Remove-Item $WatchdogPidFile -Force -ErrorAction SilentlyContinue
        }
    }

# Chat Executor Watchdog Script
# Monitors the LLM Chat Executor process and automatically restarts it if it crashes
# Usage: .\scripts\llm-chat-executor-watchdog.ps1

param(
    [int]$CheckInterval = 10,     # Check every 10 seconds
    [int]$MaxRestarts = 5,        # Maximum restarts before giving up
    [int]$RestartWindow = 300     # Reset restart count after this many seconds
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# Use APP_MODE environment variable to determine log directory
$isAdmin = $env:APP_MODE -eq "admin"
if ($isAdmin) {
    $LogDir = Join-Path $ProjectRoot "logs\admin"
} else {
    $LogDir = Join-Path $ProjectRoot "logs"
}
$PidDir = Join-Path $ProjectRoot ".pids"
$WorkerPidFile = Join-Path $PidDir "chat_executor_admin.pid"
$WatchdogPidFile = Join-Path $PidDir "chat_executor_watchdog_admin.pid"

# Ensure directories exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

# Write own PID
$PID | Out-File $WatchdogPidFile -Encoding ascii

# Restart tracking
$restartCount = 0
$lastRestartTime = Get-Date

$script:watchdogLogFile = Join-Path $LogDir "chat_executor_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# 공통 유틸리티 함수 로드 (Write-Log, Confirm-ProcessPid, Stop-ExistingProcessesByCmdline)
. (Join-Path $ScriptDir "watchdog-utils.ps1")

function Start-ChatExecutor {
    # 재시작 직전: cmdline 패턴으로 기존 프로세스 정리
    Stop-ExistingProcessesByCmdline -Label "chat executor" -CmdlinePattern 'claude_worker\.worker\.chat_executor'

    $stderrLogFile = Join-Path $LogDir "chat_executor_stderr.log"

    Write-Log "Starting Chat Executor process..."

    # Use exe alias if available, fallback to venv python
    $AliasExe = Join-Path $ProjectRoot ".venv\Scripts\monitorpage-chat.exe"
    if (Test-Path $AliasExe) {
        $VenvPython = $AliasExe
    } else {
        $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path $VenvPython)) {
            $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
        }
        if (-not (Test-Path $VenvPython)) {
            Write-Log "ERROR: Virtual environment python not found!" "ERROR"
            return $null
        }
    }

    Write-Log "Using Python: $VenvPython"

    $env:PYTHONIOENCODING = "utf-8"
    $env:APP_MODE = if ($isAdmin) { "admin" } else { "public" }

    $workerProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "app.modules.claude_worker.worker.chat_executor" `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    $actualPid = Confirm-ProcessPid -ProcessId $workerProcess.Id `
        -NamePattern 'monitorpage-chat|python' `
        -CmdlinePattern 'claude_worker\.worker\.chat_executor'

    $actualPid | Out-File $WorkerPidFile -Encoding ascii

    Write-Log "Chat Executor started with PID: $actualPid"
    return $actualPid
}

function Test-ChatExecutorRunning {
    if (-not (Test-Path $WorkerPidFile)) {
        return $false
    }

    $savedPid = Get-Content $WorkerPidFile -ErrorAction SilentlyContinue
    if (-not $savedPid) {
        return $false
    }

    $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    return ($null -ne $process)
}

# Main watchdog loop
Write-Log ("=" * 50)
Write-Log "Chat Executor Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

if (-not (Test-ChatExecutorRunning)) {
    Write-Log "Chat Executor not running, starting..." "WARN"
    Start-ChatExecutor
    $restartCount++
    $lastRestartTime = Get-Date
}

try {
    while ($true) {
        Start-Sleep -Seconds $CheckInterval

        $timeSinceLastRestart = ((Get-Date) - $lastRestartTime).TotalSeconds
        if ($timeSinceLastRestart -gt $RestartWindow) {
            if ($restartCount -gt 0) {
                Write-Log "Restart count reset (no crashes in ${RestartWindow}s)"
                $restartCount = 0
            }
        }

        if (-not (Test-ChatExecutorRunning)) {
            Write-Log "Chat Executor process died!" "ERROR"

            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Please check the chat executor logs for the root cause." "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            Write-Log "Restarting Chat Executor (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-ChatExecutor
            $restartCount++
            $lastRestartTime = Get-Date
        }
    }
}
catch {
    Write-Log "Chat Executor Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Chat Executor Watchdog stopped"
    if (Test-Path $WatchdogPidFile) {
        Remove-Item $WatchdogPidFile -Force -ErrorAction SilentlyContinue
    }
}

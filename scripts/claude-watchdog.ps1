# Claude Worker Watchdog Script
# Monitors the Claude LLM worker process and automatically restarts it if it crashes
# Usage: .\scripts\claude-watchdog.ps1

param(
    [int]$CheckInterval = 10,     # Check every 10 seconds
    [int]$MaxRestarts = 5,        # Maximum restarts before giving up
    [int]$RestartWindow = 300     # Reset restart count after this many seconds
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Use APP_MODE environment variable to determine log directory
$isAdmin = $env:APP_MODE -eq "admin"
if ($isAdmin) {
    $LogDir = Join-Path $ProjectRoot "logs\admin"
    $PidSuffix = "_admin"
} else {
    $LogDir = Join-Path $ProjectRoot "logs"
    $PidSuffix = ""
}
$PidDir = Join-Path $ProjectRoot ".pids"
$WorkerPidFile = Join-Path $PidDir "claude_worker$PidSuffix.pid"

# Ensure directories exist
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

# Restart tracking
$restartCount = 0
$lastRestartTime = Get-Date

$script:watchdogLogFile = Join-Path $LogDir "claude_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# 공통 유틸리티 함수 로드 (Write-Log, Get-DuplicateProcesses, Remove-DuplicateProcesses, Stop-ExistingProcessesByCmdline)
. (Join-Path $ScriptDir "watchdog-utils.ps1")

function Start-ClaudeWorker {
    # 재시작 직전: cmdline 패턴으로 기존 프로세스 정리 (watchdog-utils.ps1 공통 함수 사용)
    Stop-ExistingProcessesByCmdline -Label "claude worker" -CmdlinePattern 'claude_worker\.worker\.worker'

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stderrLogFile = Join-Path $LogDir "stderr_llm_worker_$Timestamp.log"

    Write-Log "Starting Claude worker process..."

    # Use exe alias if available, fallback to venv python
    $AliasExe = Join-Path $ProjectRoot ".venv\Scripts\monitorpage-claude.exe"
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

    # Set environment variables
    $env:PYTHONIOENCODING = "utf-8"
    $env:APP_MODE = if ($isAdmin) { "admin" } else { "public" }

    # Start python directly (NOT via cmd.exe) to get correct PID
    # -NoNewWindow: conhost.exe 중간 프로세스 없이 직접 실행 → PassThru PID = 실제 Python PID
    $workerProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "app.modules.claude_worker.worker.worker" `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # PID 검증: conhost 중간 프로세스 생성 여부 확인 후 실제 PID 확정
    $actualPid = Confirm-ProcessPid -ProcessId $workerProcess.Id `
        -NamePattern 'monitorpage-claude|python' `
        -CmdlinePattern 'claude_worker\.worker\.worker'

    # Save verified PID
    $actualPid | Out-File $WorkerPidFile -Encoding ascii

    # Register process in ProcessRegistry
    & $VenvPython "$ProjectRoot\scripts\register_process.py" --pid $actualPid --ppid $PID --name "claude-worker" --exe $VenvPython --role "claude" -ErrorAction SilentlyContinue

    Write-Log "Claude worker started with PID: $actualPid"
    return $actualPid
}

function Test-ClaudeWorkerRunning {
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
Write-Log "=" * 50
Write-Log "Claude Worker Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

# Initial check
if (-not (Test-ClaudeWorkerRunning)) {
    Write-Log "Claude worker not running, starting..." "WARN"
    Start-ClaudeWorker
    $restartCount++
    $lastRestartTime = Get-Date
}

try {
    while ($true) {
        Start-Sleep -Seconds $CheckInterval

        # Reset restart count if enough time has passed
        $timeSinceLastRestart = ((Get-Date) - $lastRestartTime).TotalSeconds
        if ($timeSinceLastRestart -gt $RestartWindow) {
            if ($restartCount -gt 0) {
                Write-Log "Restart count reset (no crashes in ${RestartWindow}s)"
                $restartCount = 0
            }
        }

        # Check if worker is running
        if (-not (Test-ClaudeWorkerRunning)) {
            Write-Log "Claude worker process died!" "ERROR"

            # Check restart limit
            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Please check the Claude worker logs for the root cause." "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            # Restart
            Write-Log "Restarting Claude worker (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-ClaudeWorker
            $restartCount++
            $lastRestartTime = Get-Date
        } else {
            # 프로세스가 살아있는 경우에도 중복 감지 및 정리
            Remove-DuplicateProcesses -Label "claude worker" -CmdlinePattern 'claude_worker\.worker\.worker' -PidFile $WorkerPidFile
        }
    }
}
catch {
    Write-Log "Claude Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Claude Watchdog stopped"
}

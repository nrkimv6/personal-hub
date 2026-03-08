# Command Listener Watchdog Script
# Monitors the Redis command listener process and automatically restarts if it crashes
#
# Usage: .\scripts\command-listener-watchdog.ps1

param(
    [int]$CheckInterval = 10,
    [int]$MaxRestarts = 5,
    [int]$RestartWindow = 300
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

$isAdmin = $env:APP_MODE -eq "admin"
if ($isAdmin) {
    $LogDir = Join-Path $ProjectRoot "logs\admin"
    $PidSuffix = "_admin"
} else {
    $LogDir = Join-Path $ProjectRoot "logs"
    $PidSuffix = ""
}
$PidDir = Join-Path $ProjectRoot ".pids"
$WorkerPidFile = Join-Path $PidDir "command_listener$PidSuffix.pid"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

$restartCount = 0
$lastRestartTime = Get-Date

$script:watchdogLogFile = Join-Path $LogDir "command_listener_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# 공통 유틸리티 함수 로드 (Write-Log, Get-DuplicateProcesses, Remove-DuplicateProcesses, Stop-ExistingProcessesByCmdline)
. (Join-Path $ScriptDir "watchdog-utils.ps1")

function Start-CommandListener {
    # 재시작 직전: cmdline 패턴으로 기존 프로세스 정리 (watchdog-utils.ps1 공통 함수 사용)
    Stop-ExistingProcessesByCmdline -Label "command-listener" -CmdlinePattern 'command-listener'

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_command_listener_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_command_listener_$Timestamp.log"

    Write-Log "Starting command listener process..."

    # Use exe alias if available, fallback to venv python
    $AliasExe = Join-Path $ProjectRoot ".venv\Scripts\monitorpage-cmdlistener.exe"
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

    # -NoNewWindow: conhost.exe 중간 프로세스 없이 직접 실행 → PassThru PID = 실제 Python PID
    $proc = Start-Process -FilePath $VenvPython `
        -ArgumentList "scripts\worker-command-listener.py" `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # PID 검증: conhost 중간 프로세스 생성 여부 확인 후 실제 PID 확정
    $actualPid = Confirm-ProcessPid -ProcessId $proc.Id `
        -NamePattern 'monitorpage-cmdlistener|python' `
        -CmdlinePattern 'command-listener'

    $actualPid | Out-File $WorkerPidFile -Encoding ascii

    # Register process in ProcessRegistry
    & $VenvPython "$ProjectRoot\scripts\register_process.py" --pid $actualPid --ppid $PID --name "command-listener" --exe $VenvPython --role "listener" -ErrorAction SilentlyContinue

    Write-Log "Command listener started with PID: $actualPid"
    return $actualPid
}

function Test-CommandListenerRunning {
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
Write-Log "Command Listener Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

if (-not (Test-CommandListenerRunning)) {
    Write-Log "Command listener not running, starting..." "WARN"
    Start-CommandListener
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

        if (-not (Test-CommandListenerRunning)) {
            Write-Log "Command listener process died!" "ERROR"

            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            Write-Log "Restarting command listener (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-CommandListener
            $restartCount++
            $lastRestartTime = Get-Date
        } else {
            # 프로세스가 살아있는 경우에도 중복 감지 및 정리
            Remove-DuplicateProcesses -Label "listener" -CmdlinePattern 'command-listener' -PidFile $WorkerPidFile
        }
    }
}
catch {
    Write-Log "Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Watchdog stopped"
}

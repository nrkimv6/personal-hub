# Dev Runner Command Listener Watchdog Script
# dev-runner-command-listener.py 프로세스를 감시하고 크래시 시 자동 재시작합니다.
#
# 이 watchdog는 항상 Session 1(사용자 세션)에서 실행됩니다.
# API(Session 0, SYSTEM)에서 직접 리스너를 재시작하면 SYSTEM 권한이 상속되어
# git dubious ownership 등 사용자 컨텍스트 필요 작업이 실패합니다.
# 대신 API는 Redis graceful-exit 시그널을 전송하고, 이 watchdog가 재시작을 담당합니다.
#
# Usage: .\scripts\dev-runner-listener-watchdog.ps1

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
$WatchdogPidFile = Join-Path $PidDir "dev_runner_watchdog$PidSuffix.pid"
$WorkerPidFile = Join-Path $PidDir "dev_runner_command_listener$PidSuffix.pid"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

$restartCount = 0
$lastRestartTime = Get-Date

$script:watchdogLogFile = Join-Path $LogDir "dev_runner_listener_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# 공통 유틸리티 함수 로드 (Write-Log, Stop-ExistingProcessesByCmdline, Confirm-ProcessPid)
. (Join-Path $ScriptDir "watchdog-utils.ps1")

# 이 watchdog의 PID를 파일에 기록
$PID | Out-File $WatchdogPidFile -Encoding ascii

function Start-DevRunnerListener {
    # 재시작 직전: cmdline 패턴으로 기존 프로세스 정리
    Stop-ExistingProcessesByCmdline -Label "dev-runner-listener" -CmdlinePattern 'dev-runner-command-listener\.py'

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_dev_runner_listener_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_dev_runner_listener_$Timestamp.log"

    Write-Log "Starting dev-runner-command-listener process..."

    # exe alias 우선, 없으면 venv python 사용
    $AliasExe = Join-Path $ProjectRoot ".venv\Scripts\monitorpage-devrunner-listener.exe"
    if (Test-Path $AliasExe) {
        $VenvPython = $AliasExe
        $ProcArgs = @()
    } else {
        $VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path $VenvPython)) {
            $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
        }
        if (-not (Test-Path $VenvPython)) {
            Write-Log "ERROR: Virtual environment python not found!" "ERROR"
            return $null
        }
        $ProcArgs = @("scripts\dev-runner-command-listener.py")
    }

    Write-Log "Using: $VenvPython"

    $env:PYTHONIOENCODING = "utf-8"

    # -NoNewWindow: conhost.exe 없이 직접 실행 → PassThru PID = 실제 Python PID
    $proc = Start-Process -FilePath $VenvPython `
        -ArgumentList $ProcArgs `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # PID 검증
    $actualPid = Confirm-ProcessPid -ProcessId $proc.Id `
        -NamePattern 'monitorpage-devrunner-listener|python' `
        -CmdlinePattern 'dev-runner-command-listener\.py|monitorpage-devrunner-listener'

    $actualPid | Out-File $WorkerPidFile -Encoding ascii

    # ProcessRegistry 등록
    & $VenvPython "$ProjectRoot\scripts\register_process.py" --pid $actualPid --ppid $PID --name "dev-runner-listener" --exe $VenvPython --role "dev_listener" -ErrorAction SilentlyContinue

    Write-Log "dev-runner-command-listener started with PID: $actualPid"
    return $actualPid
}

function Test-DevRunnerListenerRunning {
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
Write-Log "Dev Runner Command Listener Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

if (-not (Test-DevRunnerListenerRunning)) {
    Write-Log "dev-runner-command-listener not running, starting..." "WARN"
    Start-DevRunnerListener
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

        if (-not (Test-DevRunnerListenerRunning)) {
            Write-Log "dev-runner-command-listener process died!" "ERROR"

            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            Write-Log "Restarting dev-runner-command-listener (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-DevRunnerListener
            $restartCount++
            $lastRestartTime = Get-Date
        }
    }
}
catch {
    Write-Log "Watchdog error: $_" "ERROR"
}
finally {
    # watchdog PID 파일 정리
    if (Test-Path $WatchdogPidFile) {
        Remove-Item $WatchdogPidFile -ErrorAction SilentlyContinue
    }
    Write-Log "Watchdog stopped"
}

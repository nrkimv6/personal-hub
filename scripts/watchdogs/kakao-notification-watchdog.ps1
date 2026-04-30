# Kakao Notification Watchdog Script
# Monitors the Session 1 Kakao listener process and automatically restarts it if it dies.
#
# Usage: .\scripts\watchdogs\kakao-notification-watchdog.ps1

param(
    [int]$CheckInterval = 10,
    [int]$MaxRestarts = 5,
    [int]$RestartWindow = 300
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

$LogDir = Join-Path $ProjectRoot "logs\admin"
$PidDir = Join-Path $ProjectRoot ".pids"
$PidFile = Join-Path $PidDir "kakao_notification_listener.pid"
$GuardStateFile = Join-Path $ProjectRoot "logs\kakao_guard_state.json"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
if (-not (Test-Path $PidDir)) {
    New-Item -ItemType Directory -Path $PidDir -Force | Out-Null
}

$restartCount = 0
$lastRestartTime = Get-Date
$script:watchdogLogFile = Join-Path $LogDir "kakao_notification_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

. (Join-Path $ScriptDir "watchdog-utils.ps1")

function Clear-KakaoGuardState {
    if (Test-Path $GuardStateFile) {
        try {
            Remove-Item -LiteralPath $GuardStateFile -Force
            Write-Log "Cleared stale Kakao guard state file"
        } catch {
            Write-Log "Failed to clear Kakao guard state file: $_" "WARN"
        }
    }
}

function Start-KakaoNotificationListener {
    Stop-ExistingProcessesByCmdline -Label "kakao-notification-listener" -CmdlinePattern 'kakao-notification-listener\.py|monitorpage-kakao'
    Clear-KakaoGuardState

    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_kakao_notification_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_kakao_notification_$Timestamp.log"

    Write-Log "Starting Kakao notification listener..."

    $AliasExe = Join-Path $ProjectRoot ".venv\Scripts\monitorpage-kakao.exe"
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

    $proc = Start-Process -FilePath $VenvPython `
        -ArgumentList "scripts\services\kakao-notification-listener.py" `
        -WorkingDirectory $ProjectRoot `
        -NoNewWindow `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    $actualPid = Confirm-ProcessPid -ProcessId $proc.Id `
        -NamePattern 'monitorpage-kakao|python' `
        -CmdlinePattern 'kakao-notification-listener\.py|monitorpage-kakao'

    $actualPid | Out-File $PidFile -Encoding ascii

    & $VenvPython "$ProjectRoot\scripts\services\register_process.py" --pid $actualPid --ppid $PID --name "kakao-notification-listener" --exe $VenvPython --role "listener" -ErrorAction SilentlyContinue

    Write-Log "Kakao notification listener started with PID: $actualPid"
    return $actualPid
}

function Test-KakaoNotificationListenerRunning {
    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if (-not $savedPid) {
        return $false
    }

    $process = Get-Process -Id $savedPid -ErrorAction SilentlyContinue
    return ($null -ne $process)
}

Write-Log ("=" * 50)
Write-Log "Kakao Notification Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

if (-not (Test-KakaoNotificationListenerRunning)) {
    Write-Log "Kakao notification listener not running, starting..." "WARN"
    Start-KakaoNotificationListener
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

        if (-not (Test-KakaoNotificationListenerRunning)) {
            Write-Log "Kakao notification listener process died!" "ERROR"

            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            Write-Log "Restarting Kakao notification listener (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-KakaoNotificationListener
            $restartCount++
            $lastRestartTime = Get-Date
        }
    }
}
catch {
    Write-Log "Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Watchdog stopped"
}

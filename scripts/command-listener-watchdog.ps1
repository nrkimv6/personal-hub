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

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage -ForegroundColor $(
        switch ($Level) {
            "ERROR" { "Red" }
            "WARN"  { "Yellow" }
            "INFO"  { "Cyan" }
            default { "White" }
        }
    )
    Add-Content -Path $script:watchdogLogFile -Value $logMessage -Encoding UTF8
}

function Get-DuplicateProcesses {
    # PID 파일에 기록된 PID를 "정본"으로 간주, 나머지를 중복으로 반환
    $canonicalPid = $null
    if (Test-Path $WorkerPidFile) {
        $savedPid = Get-Content $WorkerPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $canonicalPid = [int]$savedPid
        }
    }

    $allMatching = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'command-listener' }

    if (-not $allMatching) {
        return @()
    }

    $duplicates = $allMatching | Where-Object {
        $_.ProcessId -ne $canonicalPid
    }

    return @($duplicates)
}

function Remove-DuplicateProcesses {
    $duplicates = Get-DuplicateProcesses
    if (-not $duplicates -or $duplicates.Count -eq 0) {
        return
    }

    $pids = $duplicates | ForEach-Object { $_.ProcessId }
    $pidList = $pids -join ", "
    Write-Log "중복 listener $($duplicates.Count)개 감지, 정리함 (PIDs: $pidList)" "WARN"

    foreach ($dup in $duplicates) {
        try {
            Stop-Process -Id $dup.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Log "중복 프로세스 종료: PID $($dup.ProcessId)" "WARN"
        }
        catch {
            Write-Log "중복 프로세스 종료 실패: PID $($dup.ProcessId) — $_" "ERROR"
        }
    }
}

function Start-CommandListener {
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

    $proc = Start-Process -FilePath $VenvPython `
        -ArgumentList "scripts\worker-command-listener.py" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    $proc.Id | Out-File $WorkerPidFile -Encoding ascii

    Write-Log "Command listener started with PID: $($proc.Id)"
    return $proc.Id
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
            Remove-DuplicateProcesses
        }
    }
}
catch {
    Write-Log "Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Watchdog stopped"
}

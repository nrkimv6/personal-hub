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

function Get-DuplicateClaudeWorkers {
    # PID 파일에 기록된 PID를 "정본"으로 간주, 나머지를 중복으로 반환
    $canonicalPid = $null
    if (Test-Path $WorkerPidFile) {
        $savedPid = Get-Content $WorkerPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $canonicalPid = [int]$savedPid
        }
    }

    $allMatching = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'claude_worker\.worker\.worker' }

    if (-not $allMatching) {
        return @()
    }

    $duplicates = $allMatching | Where-Object {
        $_.ProcessId -ne $canonicalPid
    }

    return @($duplicates)
}

function Remove-DuplicateClaudeWorkers {
    $duplicates = Get-DuplicateClaudeWorkers
    if (-not $duplicates -or $duplicates.Count -eq 0) {
        return
    }

    $pids = $duplicates | ForEach-Object { $_.ProcessId }
    $pidList = $pids -join ", "
    Write-Log "중복 claude worker $($duplicates.Count)개 감지, 정리함 (PIDs: $pidList)" "WARN"

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

function Start-ClaudeWorker {
    # 재시작 직전: cmdline에 'claude_worker.worker.worker'가 포함된 기존 프로세스를 모두 종료
    # 이렇게 하면 stop()을 거치지 않는 watchdog 재시작 경로에서도 중복이 생기지 않는다
    $existingProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'claude_worker\.worker\.worker' }
    if ($existingProcs) {
        $pidList = ($existingProcs | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Log "재시작 전 기존 claude worker 프로세스 정리 (PIDs: $pidList)" "WARN"
        foreach ($ep in $existingProcs) {
            try {
                Stop-Process -Id $ep.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Log "기존 프로세스 종료: PID $($ep.ProcessId)" "WARN"
            }
            catch {
                Write-Log "기존 프로세스 종료 실패: PID $($ep.ProcessId) — $_" "ERROR"
            }
        }
        Start-Sleep -Milliseconds 500
    }

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
    $workerProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "app.modules.claude_worker.worker.worker" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # Save PID - this is now the actual python process PID
    $workerProcess.Id | Out-File $WorkerPidFile -Encoding ascii

    Write-Log "Claude worker started with PID: $($workerProcess.Id)"
    return $workerProcess.Id
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
            Remove-DuplicateClaudeWorkers
        }
    }
}
catch {
    Write-Log "Claude Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Claude Watchdog stopped"
}

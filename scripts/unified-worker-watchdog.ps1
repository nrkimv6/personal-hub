# Unified Worker Watchdog Script
# Monitors the unified worker process (all workers via WorkerOrchestrator) and automatically restarts if it crashes
#
# Workers managed:
#   - NaverMonitorWorker: Naver booking monitoring/sniping
#   - ScheduledCrawlWorker: Instagram scheduled feed crawling
#   - OnDemandCrawlWorker: Instagram on-demand + Universal crawling
#
# Usage: .\scripts\unified-worker-watchdog.ps1
#
# Architecture:
#   Layer 0: This Watchdog (PowerShell) - restarts process on crash
#   Layer 1: WorkerOrchestrator - supervises worker tasks
#   Layer 2: BaseWorker._main_loop() - consecutive error tracking
#   Layer 3: Worker._safe_execute() - individual task isolation
#   Layer 4: BrowserManager - tab-level exception handling

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
$WorkerPidFile = Join-Path $PidDir "unified_worker$PidSuffix.pid"

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

# Watchdog 로그 파일 (스크립트 시작 시 1회 결정)
$script:watchdogLogFile = Join-Path $LogDir "unified_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

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
    # Also log to file
    Add-Content -Path $script:watchdogLogFile -Value $logMessage -Encoding UTF8
}

function Get-DuplicateWorkers {
    # PID 파일에 기록된 PID를 "정본"으로 간주, 나머지를 중복으로 반환
    $canonicalPid = $null
    if (Test-Path $WorkerPidFile) {
        $savedPid = Get-Content $WorkerPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $canonicalPid = [int]$savedPid
        }
    }

    $allMatching = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'app\.worker\.main' }

    if (-not $allMatching) {
        return @()
    }

    $duplicates = $allMatching | Where-Object {
        $_.ProcessId -ne $canonicalPid
    }

    return @($duplicates)
}

function Remove-DuplicateWorkers {
    $duplicates = Get-DuplicateWorkers
    if (-not $duplicates -or $duplicates.Count -eq 0) {
        return
    }

    $pids = $duplicates | ForEach-Object { $_.ProcessId }
    $pidList = $pids -join ", "
    Write-Log "중복 worker $($duplicates.Count)개 감지, 정리함 (PIDs: $pidList)" "WARN"

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

function Start-UnifiedWorker {
    # 재시작 직전: cmdline에 'app.worker.main'이 포함된 기존 프로세스를 모두 종료
    # 이렇게 하면 stop()을 거치지 않는 watchdog 재시작 경로에서도 중복이 생기지 않는다
    $existingProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'app\.worker\.main' }
    if ($existingProcs) {
        $pidList = ($existingProcs | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Log "재시작 전 기존 unified worker 프로세스 정리 (PIDs: $pidList)" "WARN"
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
    $stdoutLogFile = Join-Path $LogDir "stdout_unified_worker_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_unified_worker_$Timestamp.log"

    Write-Log "Starting unified worker process (all workers via WorkerOrchestrator)..."

    # Use exe alias if available, fallback to venv python
    $AliasExe = Join-Path $ProjectRoot ".venv\Scripts\monitorpage-worker.exe"
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

    # Start python directly - runs all workers via WorkerOrchestrator
    $workerProcess = Start-Process -FilePath $VenvPython `
        -ArgumentList "-m", "app.worker.main" `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $stderrLogFile `
        -PassThru

    # Save PID
    $workerProcess.Id | Out-File $WorkerPidFile -Encoding ascii

    Write-Log "Unified worker started with PID: $($workerProcess.Id)"
    Write-Log "  -> NaverMonitorWorker"
    Write-Log "  -> ScheduledCrawlWorker"
    Write-Log "  -> OnDemandCrawlWorker"
    return $workerProcess.Id
}

function Test-UnifiedWorkerRunning {
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

# Kill any orphaned worker processes before starting
function Stop-OrphanedWorkers {
    Write-Log "Checking for orphaned worker processes..."
    $killedCount = 0

    # Find all python processes running app.worker.main
    $pythonProcs = Get-Process -Name "python*" -ErrorAction SilentlyContinue
    foreach ($proc in $pythonProcs) {
        try {
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdLine -and $cmdLine -like "*app.worker.main*") {
                # Check if this is our managed worker
                $savedPid = if (Test-Path $WorkerPidFile) { Get-Content $WorkerPidFile -ErrorAction SilentlyContinue } else { $null }
                if ($proc.Id -ne $savedPid) {
                    Write-Log "Killing orphaned unified worker (PID: $($proc.Id))" "WARN"
                    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                    $killedCount++
                }
            }
        } catch {
            # Ignore errors
        }
    }

    if ($killedCount -gt 0) {
        Write-Log "Killed $killedCount orphaned worker(s)"
        Start-Sleep -Seconds 2  # Wait for processes to fully terminate
    }
}

# Main watchdog loop
Write-Log "=" * 50
Write-Log "Unified Worker Watchdog Started"
Write-Log "(WorkerOrchestrator Architecture)"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log "=" * 50

# Set working directory
Set-Location $ProjectRoot

# Kill orphaned workers before starting
Stop-OrphanedWorkers

# Initial check
if (-not (Test-UnifiedWorkerRunning)) {
    Write-Log "Unified worker not running, starting..." "WARN"
    Start-UnifiedWorker
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
        if (-not (Test-UnifiedWorkerRunning)) {
            Write-Log "Unified worker process died!" "ERROR"

            # Check restart limit
            if ($restartCount -ge $MaxRestarts) {
                Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                Write-Log "Please check the worker logs for the root cause." "ERROR"
                Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                break
            }

            # Restart
            Write-Log "Restarting unified worker (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
            Start-UnifiedWorker
            $restartCount++
            $lastRestartTime = Get-Date
        } else {
            # 프로세스가 살아있는 경우에도 중복 감지 및 정리
            Remove-DuplicateWorkers
        }
    }
}
catch {
    Write-Log "Watchdog error: $_" "ERROR"
}
finally {
    Write-Log "Watchdog stopped"
}

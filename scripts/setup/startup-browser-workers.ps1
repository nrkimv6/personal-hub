# Monitor Page - Startup Browser Workers
# Windows 로그인 시 브라우저 기반 워커를 자동으로 시작합니다.
# 시작 프로그램에 등록하여 사용합니다.
#
# browser_workers.py를 호출하여 watchdog 6개를 시작하고 검증합니다.
# Note: 브라우저 워커는 사용자 세션에서 실행되어야 합니다.

param(
    [int]$Delay = 20  # 서비스 시작 대기 시간 (초)
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $ProjectRoot "logs\admin\startup_browser_workers_$timestamp.log"
$browserWorkersScript = Join-Path $ScriptDir "browser_workers.py"
$apiUrl = "http://localhost:8001/health"
$apiServiceName = "MonitorPage-Admin"
$initialApiWaitSeconds = 600
$finalApiWaitSeconds = 300
$checkIntervalSeconds = 5
$startupRetryCount = 3
$startupRetrySleepSeconds = 15
$watchdogNames = @(
    "Worker Watchdog (all workers via WorkerOrchestrator)",
    "Claude Worker Watchdog",
    "Command Listener Watchdog",
    "Kakao Notification Watchdog",
    "Dev Runner Listener Watchdog",
    "Chat Executor Watchdog"
)

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"

    $logDir = Split-Path -Parent $LogFile
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Add-Content -Path $LogFile -Value $logMessage -Encoding UTF8
}

function Strip-Ansi {
    param([AllowNull()][string]$Line)

    if ($null -eq $Line) {
        return ""
    }

    $esc = [regex]::Escape([string][char]27)
    return [regex]::Replace($Line, "${esc}\[[0-9;?]*[ -/]*[@-~]", "")
}

function Invoke-BrowserWorkersCommand {
    param(
        [string]$VenvPython,
        [string]$BrowserWorkersScript,
        [string[]]$Arguments,
        [string]$LogPrefix
    )

    $output = @()
    $exitCode = -1

    try {
        $commandOutput = @(& $VenvPython $BrowserWorkersScript @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } catch {
        Write-Log "ERROR: $LogPrefix process launch failed: $_"
        throw
    }

    foreach ($line in $commandOutput) {
        $text = [string]$line
        $output += $text
        Write-Log "    [$LogPrefix] $text"
    }

    if ($output.Count -eq 0) {
        Write-Log "    [$LogPrefix] (no output)"
    }

    return @{
        Output = $output
        ExitCode = $exitCode
    }
}

function Get-WatchdogStatus {
    param(
        [string]$VenvPython,
        [string]$BrowserWorkersScript
    )

    $statusResult = Invoke-BrowserWorkersCommand `
        -VenvPython $VenvPython `
        -BrowserWorkersScript $BrowserWorkersScript `
        -Arguments @("status") `
        -LogPrefix "browser_workers.py status"

    $running = New-Object System.Collections.Generic.List[string]
    $notRunning = New-Object System.Collections.Generic.List[string]
    $raw = New-Object System.Collections.Generic.List[string]

    foreach ($line in $statusResult.Output) {
        $cleanLine = Strip-Ansi -Line ([string]$line)
        if ([string]::IsNullOrWhiteSpace($cleanLine)) {
            continue
        }

        foreach ($watchdogName in $watchdogNames) {
            if ($cleanLine -like "*$watchdogName*") {
                $raw.Add($cleanLine)
                if ($cleanLine -match '^\s*\[\+\]\s+') {
                    if (-not $running.Contains($watchdogName)) {
                        $running.Add($watchdogName)
                    }
                } elseif ($cleanLine -match '^\s*\[-\]\s+.+: Not running\s*$') {
                    if (-not $notRunning.Contains($watchdogName)) {
                        $notRunning.Add($watchdogName)
                    }
                }
                break
            }
        }
    }

    foreach ($watchdogName in $watchdogNames) {
        if (-not $running.Contains($watchdogName) -and -not $notRunning.Contains($watchdogName)) {
            $notRunning.Add($watchdogName)
            $raw.Add("[missing] $watchdogName")
        }
    }

    if ($statusResult.ExitCode -ne 0) {
        Write-Log "WARNING: browser_workers.py status exit code: $($statusResult.ExitCode)"
    }

    return @{
        Running = $running.ToArray()
        NotRunning = $notRunning.ToArray()
        Raw = $raw.ToArray()
        ExitCode = $statusResult.ExitCode
    }
}

function Write-WatchdogStatusSummary {
    param(
        [hashtable]$Status,
        [string]$Context
    )

    $summaryPrefix = if ([string]::IsNullOrWhiteSpace($Context)) {
        "Watchdog status"
    } else {
        "Watchdog status ($Context)"
    }

    $notRunningList = if ($Status.NotRunning.Count -gt 0) {
        $Status.NotRunning -join ", "
    } else {
        "-"
    }

    Write-Log "${summaryPrefix}: $($Status.Running.Count) running, $($Status.NotRunning.Count) not running ($notRunningList)"

    foreach ($line in $Status.Raw) {
        Write-Log "    [watchdog-status] $line"
    }
}

function Test-ApiServerReady {
    param([string]$ApiUrl)

    try {
        $response = Invoke-WebRequest -Uri $ApiUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Write-ServiceStatusSnapshot {
    param([string]$ServiceName)

    Write-Log "$ServiceName service status snapshot:"
    & sc.exe query $ServiceName 2>&1 | ForEach-Object { Write-Log "    $_" }
}

function Wait-ForApiServerPhase {
    param(
        [string]$ApiUrl,
        [int]$PhaseWaitSeconds,
        [int]$ElapsedSeconds,
        [int]$CheckIntervalSeconds,
        [string]$ServiceName
    )

    $phaseElapsed = 0

    while ($phaseElapsed -lt $PhaseWaitSeconds) {
        if (Test-ApiServerReady -ApiUrl $ApiUrl) {
            return @{
                Ready = $true
                ElapsedSeconds = $ElapsedSeconds + $phaseElapsed
            }
        }

        Start-Sleep -Seconds $CheckIntervalSeconds
        $phaseElapsed += $CheckIntervalSeconds
        $totalElapsed = $ElapsedSeconds + $phaseElapsed

        if ($totalElapsed % 30 -eq 0) {
            Write-Log "Still waiting for API server... ($totalElapsed seconds elapsed)"
        }

        if ($totalElapsed % 60 -eq 0) {
            Write-ServiceStatusSnapshot -ServiceName $ServiceName
        }
    }

    if (Test-ApiServerReady -ApiUrl $ApiUrl) {
        return @{
            Ready = $true
            ElapsedSeconds = $ElapsedSeconds + $phaseElapsed
        }
    }

    return @{
        Ready = $false
        ElapsedSeconds = $ElapsedSeconds + $phaseElapsed
    }
}

function Ensure-MonitorPageEventSource {
    param([string]$Source = "MonitorPage")

    try {
        if (-not [System.Diagnostics.EventLog]::SourceExists($Source)) {
            New-EventLog -LogName Application -Source $Source
            Write-Log "Created Windows Event Log source: $Source"
        }
        return $true
    } catch {
        Write-Log "WARNING: Failed to ensure Windows Event Log source '$Source': $_"
        return $false
    }
}

Write-Log "Startup browser workers script started"

# ============================================================
# STEP 0: Start Redis (Podman)
# ============================================================
Write-Log "Starting Redis via Podman..."

$redisStarted = $false

try {
    Write-Log "  Verifying Podman socket connectivity..."
    $null = & podman ps 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Log "  Podman socket OK"
    } else {
        Write-Log "  Podman socket unreachable — recycling Machine to re-establish SSH tunnel..."
        & podman machine stop 2>&1 | ForEach-Object { Write-Log "    $_" }
        Start-Sleep -Seconds 3
        & podman machine start 2>&1 | ForEach-Object { Write-Log "    $_" }
        Start-Sleep -Seconds 15

        $null = & podman ps 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "  WARNING: Podman still unreachable after recycle — workers may use SQLite fallback"
        } else {
            Write-Log "  Podman socket recovered successfully"
        }
    }

    Write-Log "  Starting Redis container..."
    Set-Location $ProjectRoot

    $PodmanCompose = Join-Path $ProjectRoot ".venv\Scripts\podman-compose.exe"
    if (-not (Test-Path $PodmanCompose)) {
        $PodmanCompose = "podman-compose"
    }

    & $PodmanCompose up -d redis 2>&1 | ForEach-Object { Write-Log "    $_" }
    Start-Sleep -Seconds 3

    Write-Log "  Testing Redis connection..."
    $pingResult = & podman exec monitor-redis redis-cli ping 2>&1
    if ($pingResult -eq "PONG") {
        Write-Log "  Redis started successfully (PONG received)"
        $redisStarted = $true
    } else {
        Write-Log "  WARNING: Redis ping failed: $pingResult"
    }
} catch {
    Write-Log "  ERROR: Redis start failed: $_"
    Write-Log "  Workers will use SQLite fallback mode"
}

if (-not $redisStarted) {
    Write-Log "  Redis not available, workers will use SQLite fallback mode"
}

# ============================================================
# STEP 1: Wait for API Server
# ============================================================
Write-Log "Waiting for API server ($apiUrl) to be ready..."

$apiWaitResult = Wait-ForApiServerPhase `
    -ApiUrl $apiUrl `
    -PhaseWaitSeconds $initialApiWaitSeconds `
    -ElapsedSeconds 0 `
    -CheckIntervalSeconds $checkIntervalSeconds `
    -ServiceName $apiServiceName

if (-not $apiWaitResult.Ready) {
    Write-Log "WARNING: API server not ready after $initialApiWaitSeconds seconds, extending wait by $finalApiWaitSeconds seconds"
    $apiWaitResult = Wait-ForApiServerPhase `
        -ApiUrl $apiUrl `
        -PhaseWaitSeconds $finalApiWaitSeconds `
        -ElapsedSeconds $apiWaitResult.ElapsedSeconds `
        -CheckIntervalSeconds $checkIntervalSeconds `
        -ServiceName $apiServiceName
}

if (-not $apiWaitResult.Ready) {
    Write-Log "ERROR: API server did not respond within 15 minutes, skipping worker start"
    return
}

Write-Log "API server is ready after $($apiWaitResult.ElapsedSeconds) seconds"

# ============================================================
# STEP 2: Start browser_workers.py and verify watchdogs
# ============================================================
Write-Log "Starting browser workers via browser_workers.py..."

$VenvScripts = Join-Path $ProjectRoot ".venv\Scripts"
if (-not (Test-Path $VenvScripts)) {
    $VenvScripts = Join-Path $ProjectRoot "venv\Scripts"
}
$VenvPython = Join-Path $VenvScripts "python.exe"

$WorkerAliasExe = Join-Path $VenvScripts "monitorpage-worker.exe"
if (Test-Path $WorkerAliasExe) {
    Write-Log "Using alias exe: monitorpage-worker.exe"
    $VenvPython = $WorkerAliasExe
} else {
    Write-Log "Alias exe not found, using python.exe (run setup-exe-aliases.ps1 to enable process identification)"
}

try {
    $startResult = Invoke-BrowserWorkersCommand `
        -VenvPython $VenvPython `
        -BrowserWorkersScript $browserWorkersScript `
        -Arguments @("start") `
        -LogPrefix "browser_workers.py start"
} catch {
    Write-Log "ERROR: Failed to start browser workers process: $_"
    return
}

if ($startResult.ExitCode -ne 0) {
    Write-Log "ERROR: browser_workers.py start exit code: $($startResult.ExitCode)"
}

Start-Sleep -Seconds 5
$watchdogStatus = Get-WatchdogStatus -VenvPython $VenvPython -BrowserWorkersScript $browserWorkersScript
Write-WatchdogStatusSummary -Status $watchdogStatus -Context "initial"

$retryAttempt = 0
while ($watchdogStatus.NotRunning.Count -gt 0 -and $retryAttempt -lt $startupRetryCount) {
    $retryAttempt += 1
    Write-Log "WARNING: retrying $retryAttempt/$startupRetryCount for: $($watchdogStatus.NotRunning -join ', ')"
    Start-Sleep -Seconds $startupRetrySleepSeconds

    try {
        $retryStartResult = Invoke-BrowserWorkersCommand `
            -VenvPython $VenvPython `
            -BrowserWorkersScript $browserWorkersScript `
            -Arguments @("start") `
            -LogPrefix "browser_workers.py start retry $retryAttempt"
    } catch {
        Write-Log "ERROR: Failed to start browser workers process on retry ${retryAttempt}: $_"
        continue
    }

    if ($retryStartResult.ExitCode -ne 0) {
        Write-Log "ERROR: browser_workers.py start retry $retryAttempt exit code: $($retryStartResult.ExitCode)"
    }

    Start-Sleep -Seconds 5
    $watchdogStatus = Get-WatchdogStatus -VenvPython $VenvPython -BrowserWorkersScript $browserWorkersScript
    Write-WatchdogStatusSummary -Status $watchdogStatus -Context "after retry $retryAttempt"
}

if ($watchdogStatus.NotRunning.Count -gt 0) {
    $failedWatchdogs = $watchdogStatus.NotRunning -join ", "
    Write-Log "ERROR: watchdogs failed to start after 3 retries: $failedWatchdogs"

    if (Ensure-MonitorPageEventSource -Source "MonitorPage") {
        try {
            Write-EventLog `
                -LogName Application `
                -Source "MonitorPage" `
                -EventId 7001 `
                -EntryType Warning `
                -Message "Watchdog startup failed: $failedWatchdogs"
            Write-Log "Wrote Windows Event Log warning for failed watchdog startup"
        } catch {
            Write-Log "WARNING: Failed to write Windows Event Log entry: $_"
        }
    }
} else {
    Write-Log "All watchdogs verified as running after startup"
}

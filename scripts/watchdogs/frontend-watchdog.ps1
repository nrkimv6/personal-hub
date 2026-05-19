# Frontend Memory-Aware Watchdog
# Monitors both ADMIN DEV (:6101) and PUBLIC PREVIEW (:6100) frontends.

param(
    [int]$CheckInterval = 30,
    [int]$Timeout = 10,
    [double]$MemoryRestartThresholdMb = 1500,
    [int]$BackoffWindowMin = 5,
    [int]$BackoffMaxFailures = 3,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

. (Join-Path $ProjectRoot "scripts\setup\Send-TelegramAlert.ps1")
. (Join-Path $ScriptDir "frontend-watchdog-lib.ps1")

$thresholdOverride = $env:FRONTEND_WATCHDOG_THRESHOLD_MB
if ($thresholdOverride) {
    try { $MemoryRestartThresholdMb = [double]$thresholdOverride } catch {}
}
$holdPollSeconds = if ($env:FRONTEND_WATCHDOG_HOLD_POLL_SECONDS) { [int]$env:FRONTEND_WATCHDOG_HOLD_POLL_SECONDS } else { 60 }
$holdTimeoutSeconds = if ($env:FRONTEND_WATCHDOG_HOLD_TIMEOUT_SECONDS) { [int]$env:FRONTEND_WATCHDOG_HOLD_TIMEOUT_SECONDS } else { 1800 }
$pauseMinutes = if ($env:FRONTEND_WATCHDOG_PAUSE_MINUTES) { [int]$env:FRONTEND_WATCHDOG_PAUSE_MINUTES } else { 60 }
$alertCooldownSeconds = if ($env:FRONTEND_WATCHDOG_ALERT_COOLDOWN_SECONDS) { [int]$env:FRONTEND_WATCHDOG_ALERT_COOLDOWN_SECONDS } else { 600 }

$LogDir = Join-Path $ProjectRoot "logs\admin"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$script:WatchdogLogFile = Join-Path $LogDir "frontend_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$script:lastAlertTime = @{}
$script:restartHistory = @{
    6101 = @()
    6100 = @()
}
$script:pausedUntil = @{}
$script:holdAlertState = @{}
$script:portConfig = @{
    6101 = @{
        Name = "ADMIN DEV"
        Public = $false
        Url = "http://127.0.0.1:6101"
        PidFile = Join-Path $ProjectRoot ".pids\frontend_admin.pid"
    }
    6100 = @{
        Name = "PUBLIC PREVIEW"
        Public = $true
        Url = "http://127.0.0.1:6100"
        PidFile = Join-Path $ProjectRoot ".pids\frontend.pid"
    }
}

function Write-WatchdogLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )

    if ($Level -eq "DEBUG" -and -not $Verbose) {
        return
    }

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] [$Level] $Message"
    $color = switch ($Level) {
        "ERROR" { "Red" }
        "WARN" { "Yellow" }
        "OK" { "Green" }
        "DEBUG" { "DarkGray" }
        default { "Cyan" }
    }
    Write-Host $line -ForegroundColor $color
    Add-Content -Path $script:WatchdogLogFile -Value $line -Encoding UTF8
}

function Test-ShouldAlert {
    param([string]$Key)
    $last = $script:lastAlertTime[$Key]
    if ($last -and (((Get-Date) - $last).TotalSeconds -lt $alertCooldownSeconds)) {
        return $false
    }
    return $true
}

function Show-FrontendPopup {
    param(
        [string]$Title,
        [string]$Message
    )

    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
        [void][System.Windows.Forms.MessageBox]::Show($Message, $Title, "OK", "Warning")
    } catch {
        Write-WatchdogLog "Popup failed: $($_.Exception.Message)" "DEBUG"
    }
}

function Convert-TopProcessesToText {
    param([object[]]$TopProcesses)

    if (-not $TopProcesses) {
        return "(no top processes)"
    }

    return (($TopProcesses | Select-Object -First 5 | ForEach-Object {
        $scriptPath = if ($_.script_path) { " [$($_.script_path)]" } else { "" }
        "PID=$($_.pid) $($_.name)$scriptPath $($_.memory_mb)MB"
    }) -join "`n")
}

function Send-FrontendAlert {
    param(
        [string]$Kind,
        [int]$Port,
        [double]$AvailableMb = 0,
        [object[]]$TopProcesses = @(),
        [string]$ExtraMessage = ""
    )

    $config = $script:portConfig[$Port]
    $alertKey = "$Kind-$Port"
    if (-not (Test-ShouldAlert $alertKey)) {
        return
    }

    $title = "Frontend Watchdog: $($config.Name)"
    $body = switch ($Kind) {
        "death" {
            "Frontend listener died ($($config.Name), port $Port).`nAvailable=${AvailableMb}MB`n$ExtraMessage"
        }
        "hold" {
            "Frontend restart held due to low memory ($($config.Name), port $Port).`nAvailable=${AvailableMb}MB / Threshold=${MemoryRestartThresholdMb}MB`n$ExtraMessage"
        }
        "stopped" {
            "Frontend auto-restart stopped ($($config.Name), port $Port). Manual intervention required.`nAvailable=${AvailableMb}MB`n$ExtraMessage"
        }
        "enoent-pause" {
            "Frontend auto-restart paused after repeated SvelteKit write_types ENOENT crashes ($($config.Name), port $Port).`nAvailable=${AvailableMb}MB`n$ExtraMessage"
        }
        default {
            "$Kind ($($config.Name), port $Port)`n$ExtraMessage"
        }
    }
    $topText = Convert-TopProcessesToText $TopProcesses
    $message = "$title`n$body`nTop:`n$topText"
    [void](Send-TelegramAlert $message)

    if ($Kind -in @("hold", "stopped", "death")) {
        Show-FrontendPopup -Title $title -Message $body
    }

    $script:lastAlertTime[$alertKey] = Get-Date
}

function Get-MemorySnapshot {
    $snapshotScript = Join-Path $ProjectRoot "scripts\diagnostics\memory_snapshot.py"
    try {
        $raw = & $PythonExe $snapshotScript --json 2>$null
        if (-not $raw) {
            return $null
        }
        return $raw | ConvertFrom-Json
    } catch {
        Write-WatchdogLog "Memory snapshot failed: $($_.Exception.Message)" "WARN"
        return $null
    }
}

function Get-FrontendListenerPid {
    param([int]$Port)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
            Where-Object { $_.State -eq "Listen" } |
            Select-Object -First 1
        if ($conn) {
            return [int]$conn.OwningProcess
        }
    } catch {
        Write-WatchdogLog "Port query failed for ${Port}: $($_.Exception.Message)" "DEBUG"
    }
    return 0
}

function Test-FrontendHealth {
    param([int]$Port)

    $config = $script:portConfig[$Port]
    $listenerPid = Get-FrontendListenerPid -Port $Port
    $httpOk = $false
    try {
        $response = Invoke-WebRequest -Uri $config.Url -TimeoutSec $Timeout -UseBasicParsing -ErrorAction Stop
        $httpOk = $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
    } catch {
        $httpOk = $false
    }

    [pscustomobject]@{
        Port = $Port
        Name = $config.Name
        Url = $config.Url
        ListenerPid = $listenerPid
        HttpOk = $httpOk
        Healthy = ($listenerPid -gt 0 -and $httpOk)
    }
}

function Register-RestartAttempt {
    param([int]$Port)

    $now = Get-Date
    $cutoff = $now.AddMinutes(-$BackoffWindowMin)
    $history = @($script:restartHistory[$Port] | Where-Object { $_ -ge $cutoff })
    $history += $now
    $script:restartHistory[$Port] = $history
    return $history.Count
}

function Test-BackoffExceeded {
    param([int]$Port)

    $now = Get-Date
    $cutoff = $now.AddMinutes(-$BackoffWindowMin)
    $history = @($script:restartHistory[$Port] | Where-Object { $_ -ge $cutoff })
    $script:restartHistory[$Port] = $history
    return ($history.Count -ge $BackoffMaxFailures)
}

function Invoke-FrontendRestart {
    param([int]$Port)

    $config = $script:portConfig[$Port]
    if (Test-BackoffExceeded -Port $Port) {
        $isEnoentPause = Test-ShouldShortBackoff -LogDir $LogDir
        $effectivePauseMinutes = if ($isEnoentPause) { Get-FrontendBackoffPauseMinutes -StandardPauseMinutes $pauseMinutes } else { $pauseMinutes }
        $pausedUntil = (Get-Date).AddMinutes($effectivePauseMinutes)
        $script:pausedUntil[$Port] = $pausedUntil
        $alertKind = if ($isEnoentPause) { "enoent-pause" } else { "stopped" }
        Send-FrontendAlert -Kind $alertKind -Port $Port -ExtraMessage "Backoff exceeded: ${BackoffMaxFailures} failures within ${BackoffWindowMin} minutes. Paused ${effectivePauseMinutes} minutes until $($pausedUntil.ToString('s'))."
        Write-WatchdogLog "Paused frontend restart for $Port until $($pausedUntil.ToString('s')) due to backoff (minutes=$effectivePauseMinutes, enoent=$isEnoentPause)." "ERROR"
        return $false
    }

    $holdStartedAt = Get-Date
    while ($true) {
        $snapshot = Get-MemorySnapshot
        if (-not $snapshot) {
            break
        }
        $availableMb = [double]$snapshot.available_mb
        if ($availableMb -ge $MemoryRestartThresholdMb) {
            break
        }

        $elapsed = ((Get-Date) - $holdStartedAt).TotalSeconds
        $extra = "Hold elapsed: $([int]$elapsed)s. Waiting for memory recovery before restart."
        if (-not $script:holdAlertState[$Port]) {
            Send-FrontendAlert -Kind "hold" -Port $Port -AvailableMb $availableMb -TopProcesses $snapshot.top_processes -ExtraMessage $extra
            $script:holdAlertState[$Port] = $true
        }
        Write-WatchdogLog "Holding frontend restart for ${Port}: available=${availableMb}MB threshold=${MemoryRestartThresholdMb}MB elapsed=${elapsed}s" "WARN"

        if ($elapsed -ge $holdTimeoutSeconds) {
            $pausedUntil = (Get-Date).AddMinutes($pauseMinutes)
            $script:pausedUntil[$Port] = $pausedUntil
            Send-FrontendAlert -Kind "stopped" -Port $Port -AvailableMb $availableMb -TopProcesses $snapshot.top_processes -ExtraMessage "Memory did not recover within ${holdTimeoutSeconds}s. Paused until $($pausedUntil.ToString('s'))."
            Write-WatchdogLog "Memory hold timeout for $Port. Paused until $($pausedUntil.ToString('s'))." "ERROR"
            return $false
        }
        Start-Sleep -Seconds $holdPollSeconds
    }

    $script:holdAlertState[$Port] = $false
    $attemptCount = Register-RestartAttempt -Port $Port
    $commandArgs = @((Join-Path $ProjectRoot "scripts\services\browser_workers.py"), "restart-frontend")
    if ($config.Public) {
        $commandArgs += "--public"
    }
    Write-WatchdogLog "Restarting frontend for $Port (attempt window count=$attemptCount)." "WARN"
    & $PythonExe @commandArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-WatchdogLog "Frontend restart command failed for $Port (exit=$exitCode)." "ERROR"
        if (Test-BackoffExceeded -Port $Port) {
            $isEnoentPause = Test-ShouldShortBackoff -LogDir $LogDir
            $effectivePauseMinutes = if ($isEnoentPause) { Get-FrontendBackoffPauseMinutes -StandardPauseMinutes $pauseMinutes } else { $pauseMinutes }
            $pausedUntil = (Get-Date).AddMinutes($effectivePauseMinutes)
            $script:pausedUntil[$Port] = $pausedUntil
            $alertKind = if ($isEnoentPause) { "enoent-pause" } else { "stopped" }
            Send-FrontendAlert -Kind $alertKind -Port $Port -ExtraMessage "Restart command failed repeatedly. Paused ${effectivePauseMinutes} minutes until $($pausedUntil.ToString('s'))."
        }
        return $false
    }

    Start-Sleep -Seconds 15
    $postHealth = Test-FrontendHealth -Port $Port
    if (-not $postHealth.Healthy) {
        Write-WatchdogLog "Frontend still unhealthy after restart on $Port." "WARN"
        return $false
    }

    Write-WatchdogLog "Frontend recovered on $Port (PID=$($postHealth.ListenerPid))." "OK"
    return $true
}

$banner = @(
    ""
    "========================================"
    "  Frontend Memory-Aware Watchdog Started"
    "  Ports: 6101(admin), 6100(public)"
    "  Check Interval: ${CheckInterval}s"
    "  Threshold: ${MemoryRestartThresholdMb}MB"
    "  Log File: $($script:WatchdogLogFile)"
    "========================================"
    ""
)
foreach ($line in $banner) {
    Write-Host $line -ForegroundColor Cyan
    Add-Content -Path $script:WatchdogLogFile -Value $line -Encoding UTF8
}

while ($true) {
    foreach ($port in @(6101, 6100)) {
        $pausedUntil = $script:pausedUntil[$port]
        if ($pausedUntil -and $pausedUntil -gt (Get-Date)) {
            Write-WatchdogLog "Port $port is paused until $($pausedUntil.ToString('s'))." "DEBUG"
            continue
        }

        $health = Test-FrontendHealth -Port $port
        if ($health.Healthy) {
            Write-WatchdogLog "Frontend healthy: $($health.Name) port=$port pid=$($health.ListenerPid)" "DEBUG"
            continue
        }

        $snapshot = Get-MemorySnapshot
        $availableMb = if ($snapshot) { [double]$snapshot.available_mb } else { 0 }
        $topProcesses = if ($snapshot) { $snapshot.top_processes } else { @() }
        Send-FrontendAlert -Kind "death" -Port $port -AvailableMb $availableMb -TopProcesses $topProcesses -ExtraMessage "ListenerPid=$($health.ListenerPid) HttpOk=$($health.HttpOk)"
        [void](Invoke-FrontendRestart -Port $port)
    }
    Start-Sleep -Seconds $CheckInterval
}

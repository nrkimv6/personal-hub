param(
    [int]$CheckInterval = 10,
    [int]$MaxRestarts = 5,
    [int]$RestartWindow = 300
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

. (Join-Path $ScriptDir "watchdog-utils.ps1")

$paths = Get-WatchdogPaths -ProjectRoot $ProjectRoot
$LogDir = $paths.LogDir
$PidDir = $paths.PidDir
$PidSuffix = $paths.PidSuffix
$WatchdogPidFile = Join-Path $PidDir "dev_runner_watchdog$PidSuffix.pid"
$WorkerPidFile = Join-Path $PidDir "dev_runner_command_listener$PidSuffix.pid"

$script:watchdogLogFile = Join-Path $LogDir "dev_runner_listener_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

$PID | Out-File $WatchdogPidFile -Encoding ascii

function Start-DevRunnerListener {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_dev_runner_listener_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_dev_runner_listener_$Timestamp.log"

    Write-Log "Starting dev-runner-command-listener process..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot -AliasName "monitorpage-devrunner-listener.exe"
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    if ($VenvPython -match "monitorpage-devrunner-listener\.exe$") {
        $ProcArgs = @()
    } else {
        $ProcArgs = @("scripts\plan_runner\dev-runner-command-listener.py")
    }
    Write-Log "Using: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "dev-runner-listener" `
        -Python $VenvPython `
        -ArgList $ProcArgs `
        -WorkingDir $ProjectRoot `
        -StdoutLog $stdoutLogFile `
        -StderrLog $stderrLogFile `
        -NamePattern 'monitorpage-devrunner-listener|python' `
        -CmdlinePattern 'dev-runner-command-listener\.py|monitorpage-devrunner-listener' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8" } `
        -RegisterRole "dev_listener" `
        -RegisterName "dev-runner-listener" `
        -ParentPid $PID

    Write-Log "dev-runner-command-listener started with PID: $actualPid"
    return $actualPid
}

# Main watchdog loop
Write-Log ("=" * 50)
Write-Log "Dev Runner Command Listener Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "dev-runner-command-listener" `
    -StartTarget { Start-DevRunnerListener } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow `
    -OnExit {
        if (Test-Path $WatchdogPidFile) {
            Remove-Item $WatchdogPidFile -ErrorAction SilentlyContinue
        }
    }

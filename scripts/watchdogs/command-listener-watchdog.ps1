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
$WorkerPidFile = Join-Path $PidDir "command_listener$PidSuffix.pid"
$script:watchdogLogFile = Join-Path $LogDir "command_listener_watchdog_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

function Start-CommandListener {
    $Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $stdoutLogFile = Join-Path $LogDir "stdout_command_listener_$Timestamp.log"
    $stderrLogFile = Join-Path $LogDir "stderr_command_listener_$Timestamp.log"

    Write-Log "Starting command listener process..."

    $VenvPython = Get-WorkerExecutable -ProjectRoot $ProjectRoot -AliasName "monitorpage-cmdlistener.exe"
    if (-not $VenvPython) {
        Write-Log "ERROR: Virtual environment python not found!" "ERROR"
        return $null
    }
    Write-Log "Using Python: $VenvPython"

    $actualPid = Start-WorkerProcess `
        -Label "command-listener" `
        -Python $VenvPython `
        -ArgList @("scripts\services\worker-command-listener.py") `
        -WorkingDir $ProjectRoot `
        -StdoutLog $stdoutLogFile `
        -StderrLog $stderrLogFile `
        -NamePattern 'monitorpage-cmdlistener|python' `
        -CmdlinePattern 'worker-command-listener\.py|monitorpage-cmdlistener' `
        -PidFile $WorkerPidFile `
        -Env @{ PYTHONIOENCODING = "utf-8" } `
        -RegisterRole "listener" `
        -RegisterName "command-listener" `
        -ParentPid $PID

    Write-Log "Command listener started with PID: $actualPid"
    return $actualPid
}

# Main watchdog loop
Write-Log ("=" * 50)
Write-Log "Command Listener Watchdog Started"
Write-Log "Check interval: ${CheckInterval}s"
Write-Log "Max restarts: $MaxRestarts in ${RestartWindow}s"
Write-Log ("=" * 50)

Set-Location $ProjectRoot

Invoke-WatchdogLoop `
    -Label "Command listener" `
    -StartTarget { Start-CommandListener } `
    -TestRunning { Test-PidFileAlive -PidFile $WorkerPidFile } `
    -CheckInterval $CheckInterval `
    -MaxRestarts $MaxRestarts `
    -RestartWindow $RestartWindow

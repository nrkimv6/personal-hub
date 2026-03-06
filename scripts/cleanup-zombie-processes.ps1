# cleanup-zombie-processes.ps1
# Scan and kill zombie/orphan processes (pytest, old node, stale python)
#
# Usage:
#   .\scripts\cleanup-zombie-processes.ps1              # dry-run (show only)
#   .\scripts\cleanup-zombie-processes.ps1 -Kill        # actually kill
#   .\scripts\cleanup-zombie-processes.ps1 -MaxAgeHours 12  # 12h+ only

param(
    [switch]$Kill,
    [int]$MaxAgeHours = 24
)

$Now = Get-Date
$Cutoff = $Now.AddHours(-$MaxAgeHours)
$CutoffStr = $Cutoff.ToString('MM/dd HH:mm')

Write-Host "=== Zombie Process Scanner ===" -ForegroundColor Cyan
Write-Host "  Threshold: ${MaxAgeHours}h+ (before $CutoffStr)" -ForegroundColor Gray
if ($Kill) {
    Write-Host "  Mode: KILL" -ForegroundColor Red
} else {
    Write-Host "  Mode: DRY-RUN (show only)" -ForegroundColor Yellow
}
Write-Host ""

$AllTargets = @()

function Get-TruncatedCmd($cmd, $maxLen = 80) {
    if (-not $cmd) { return '' }
    if ($cmd.Length -gt $maxLen) { return $cmd.Substring(0, $maxLen) + '...' }
    return $cmd
}

function Get-AgeString($startTime) {
    $hours = [math]::Round(($Now - $startTime).TotalHours, 1)
    return "${hours}h"
}

# --- 1. Zombie pytest ---
Write-Host "[1] Scanning zombie pytest..." -ForegroundColor Cyan
$pytestProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*pytest*'
} | ForEach-Object {
    $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    if ($proc -and $proc.StartTime -and $proc.StartTime -lt $Cutoff) {
        [PSCustomObject]@{
            Type      = 'pytest'
            PID       = $_.ProcessId
            MemMB     = [math]::Round($_.WorkingSetSize / 1MB)
            StartTime = $proc.StartTime
            Age       = Get-AgeString $proc.StartTime
            Command   = Get-TruncatedCmd $_.CommandLine
        }
    }
}
if ($pytestProcs) { $AllTargets += @($pytestProcs) }

# --- 2. Old node processes ---
Write-Host "[2] Scanning old node processes..." -ForegroundColor Cyan
$nodeProcs = Get-Process -Name 'node' -ErrorAction SilentlyContinue | Where-Object {
    $_.StartTime -and $_.StartTime -lt $Cutoff
} | ForEach-Object {
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)" -ErrorAction SilentlyContinue
    [PSCustomObject]@{
        Type      = 'node'
        PID       = $_.Id
        MemMB     = [math]::Round($_.WorkingSet64 / 1MB)
        StartTime = $_.StartTime
        Age       = Get-AgeString $_.StartTime
        Command   = Get-TruncatedCmd $cim.CommandLine
    }
}
if ($nodeProcs) { $AllTargets += @($nodeProcs) }

# --- 3. Orphan python (monitor-page related, not services) ---
Write-Host "[3] Scanning orphan python processes..." -ForegroundColor Cyan
$ServicePatterns = @('service_run.py', 'app.worker.main', 'claude_worker', 'command-listener', 'watchdog', 'dev-runner-command')
$pythonProcs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -like 'python*' -or $_.Name -like 'monitorpage-*') -and $_.CommandLine -like '*monitor-page*'
} | ForEach-Object {
    $cmd = $_.CommandLine
    $isService = $false
    foreach ($pat in $ServicePatterns) {
        if ($cmd -like "*$pat*") { $isService = $true; break }
    }
    if (-not $isService) {
        $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        if ($proc -and $proc.StartTime -and $proc.StartTime -lt $Cutoff) {
            [PSCustomObject]@{
                Type      = 'python'
                PID       = $_.ProcessId
                MemMB     = [math]::Round($_.WorkingSetSize / 1MB)
                StartTime = $proc.StartTime
                Age       = Get-AgeString $proc.StartTime
                Command   = Get-TruncatedCmd $cmd
            }
        }
    }
}
if ($pythonProcs) { $AllTargets += @($pythonProcs) }

# --- Results ---
Write-Host ""
if ($AllTargets.Count -eq 0) {
    Write-Host "No zombie processes found." -ForegroundColor Green
    exit 0
}

$count = $AllTargets.Count
Write-Host "Found: $count targets" -ForegroundColor Yellow
Write-Host ""
$AllTargets | Sort-Object StartTime | Format-Table -Property Type, PID, MemMB, Age, StartTime, Command -AutoSize

if (-not $Kill) {
    Write-Host "[dry-run] To kill: .\scripts\cleanup-zombie-processes.ps1 -Kill" -ForegroundColor Yellow
    exit 0
}

# --- Kill ---
Write-Host "Killing processes..." -ForegroundColor Red
$killed = 0
foreach ($target in $AllTargets) {
    try {
        Stop-Process -Id $target.PID -Force -ErrorAction Stop
        Write-Host "  Killed PID $($target.PID) ($($target.Type), $($target.Age))" -ForegroundColor Green
        $killed++
    } catch {
        Write-Host "  Failed PID $($target.PID): $($_.Exception.Message)" -ForegroundColor Red
    }
}
Write-Host ""
Write-Host "Done: $killed / $count killed" -ForegroundColor Green

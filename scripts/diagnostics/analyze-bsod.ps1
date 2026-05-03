# BSOD event correlation analyzer
# Correlates System event log providers around crash timestamps without requiring admin rights.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\scripts\diagnostics\analyze-bsod.ps1
#   powershell -ExecutionPolicy Bypass -File .\scripts\diagnostics\analyze-bsod.ps1 -Days 90 -Top 10
#   powershell -ExecutionPolicy Bypass -File .\scripts\diagnostics\analyze-bsod.ps1 -OutputFile docs\reports\bsod-report.txt

param(
    [int]$Days = 30,
    [int]$Top = 5,
    [int]$WindowSec = 60,
    [string]$OutputFile
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Get-BugCheckCode {
    param([System.Diagnostics.Eventing.Reader.EventRecord]$Event)

    $message = $Event.Message
    if ($message -match '(?i)bugcheck(?:\s+was)?:?\s*(0x[0-9a-f]+)') {
        return $Matches[1]
    }
    if ($message -match '(?i)BugcheckCode\s+(\d+)') {
        return ("0x{0:X}" -f [int]$Matches[1])
    }
    foreach ($prop in $Event.Properties) {
        if ($null -ne $prop.Value -and $prop.Value -is [int] -and [int]$prop.Value -gt 0) {
            return ("0x{0:X}" -f [int]$prop.Value)
        }
    }
    return ""
}

function Get-BugCheckHint {
    param([string]$Code)

    $map = @{
        "0xA"   = "IRQL_NOT_LESS_OR_EQUAL: driver memory access at invalid IRQL"
        "0x1E"  = "KMODE_EXCEPTION_NOT_HANDLED: kernel-mode exception"
        "0x3B"  = "SYSTEM_SERVICE_EXCEPTION: driver/system service exception"
        "0x7E"  = "SYSTEM_THREAD_EXCEPTION_NOT_HANDLED"
        "0x9F"  = "DRIVER_POWER_STATE_FAILURE"
        "0xD1"  = "DRIVER_IRQL_NOT_LESS_OR_EQUAL"
        "0x139" = "KERNEL_SECURITY_CHECK_FAILURE"
    }
    if ($map.ContainsKey($Code)) { return $map[$Code] }
    return ""
}

function Get-BsodEvents {
    param([datetime]$Since)

    $ids = 41, 1001, 6008
    $filter = @{
        LogName = "System"
        Id = $ids
        StartTime = $Since
    }

    try {
        $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
    } catch {
        Write-Warning "Failed to read System event log: $_"
        return @()
    }

    $rows = @()
    foreach ($event in $events) {
        $code = Get-BugCheckCode -Event $event
        $rows += [pscustomobject]@{
            TimeCreated = $event.TimeCreated
            Id = $event.Id
            ProviderName = $event.ProviderName
            BugCheckCode = $code
            Hint = Get-BugCheckHint -Code $code
            Message = (($event.Message -replace '\s+', ' ').Trim())
        }
    }

    return @($rows | Sort-Object TimeCreated)
}

function Get-CorrelatedEvents {
    param(
        [array]$BsodEvents,
        [int]$WindowSeconds
    )

    $all = @()
    foreach ($bsod in $BsodEvents) {
        $start = $bsod.TimeCreated.AddSeconds(-1 * $WindowSeconds)
        $end = $bsod.TimeCreated.AddSeconds($WindowSeconds)
        $filter = @{
            LogName = "System"
            Level = 1, 2
            StartTime = $start
            EndTime = $end
        }

        try {
            $events = Get-WinEvent -FilterHashtable $filter -ErrorAction SilentlyContinue
        } catch {
            Write-Warning "Failed to query correlated events ($($bsod.TimeCreated)): $_"
            continue
        }

        $seenForCrash = @{}
        foreach ($event in $events) {
            if ($event.Id -in 41, 1001, 6008) { continue }
            $key = "{0}|{1}" -f $event.ProviderName, $event.Id
            if ($seenForCrash.ContainsKey($key)) { continue }
            $seenForCrash[$key] = $true

            $all += [pscustomobject]@{
                BsodTime = $bsod.TimeCreated
                EventTime = $event.TimeCreated
                DeltaSeconds = [math]::Round(($event.TimeCreated - $bsod.TimeCreated).TotalSeconds, 1)
                Id = $event.Id
                ProviderName = $event.ProviderName
                LevelDisplayName = $event.LevelDisplayName
                Message = (($event.Message -replace '\s+', ' ').Trim())
            }
        }
    }

    return @($all | Sort-Object BsodTime, EventTime)
}

function Find-SuspectDrivers {
    param(
        [array]$CorrelatedEvents,
        [int]$CrashCount
    )

    if ($CrashCount -le 0) { return @() }

    $ranked = $CorrelatedEvents |
        Group-Object ProviderName |
        ForEach-Object {
            $crashHits = @($_.Group | Select-Object -ExpandProperty BsodTime -Unique).Count
            [pscustomobject]@{
                ProviderName = $_.Name
                CrashHits = $crashHits
                EventCount = $_.Count
                HitRate = [math]::Round(($crashHits / $CrashCount) * 100, 1)
                EventIds = (($_.Group | Select-Object -ExpandProperty Id -Unique | Sort-Object) -join ",")
            }
        } |
        Sort-Object @{ Expression = "CrashHits"; Descending = $true }, @{ Expression = "EventCount"; Descending = $true }, ProviderName

    return @($ranked)
}

function Get-DriverDetail {
    param([string]$ProviderName)

    $escaped = $ProviderName -replace "'", "''"
    $details = @()

    try {
        $details += @(Get-CimInstance Win32_SystemDriver -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "*$ProviderName*" -or $_.DisplayName -like "*$ProviderName*" -or $_.PathName -like "*$ProviderName*" } |
            Select-Object @{n="Kind";e={"SystemDriver"}}, Name, DisplayName, State, StartMode, PathName)
    } catch {
        Write-Verbose "Win32_SystemDriver query failed: $_"
    }

    try {
        $details += @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
            Where-Object { $_.DeviceName -like "*$ProviderName*" -or $_.DriverProviderName -like "*$ProviderName*" -or $_.InfName -like "*$ProviderName*" } |
            Select-Object @{n="Kind";e={"PnPSignedDriver"}}, DeviceName, DriverProviderName, DriverVersion, DriverDate, InfName)
    } catch {
        Write-Verbose "Win32_PnPSignedDriver query failed: $_"
    }

    if ($details.Count -eq 0 -and $escaped) {
        return @([pscustomobject]@{ ProviderName = $ProviderName; Detail = "No matching driver detail found" })
    }
    return @($details)
}

function Get-MemoryPressureContext {
    param([array]$BsodEvents)

    $path = Join-Path $ProjectRoot "logs\memory_pressure_events.jsonl"
    if (-not (Test-Path $path)) { return @() }

    $rows = @()
    foreach ($line in Get-Content -LiteralPath $path -ErrorAction SilentlyContinue) {
        if (-not $line.Trim()) { continue }
        try {
            $item = $line | ConvertFrom-Json
        } catch {
            continue
        }

        $rawTime = $item.timestamp
        if (-not $rawTime) { $rawTime = $item.recorded_at }
        if (-not $rawTime) { $rawTime = $item.captured_at }
        if (-not $rawTime) { continue }

        try {
            $ts = [datetime]::Parse($rawTime)
        } catch {
            continue
        }

        foreach ($bsod in $BsodEvents) {
            $delta = [math]::Abs(($ts - $bsod.TimeCreated).TotalMinutes)
            if ($delta -le 5) {
                $rows += [pscustomobject]@{
                    BsodTime = $bsod.TimeCreated
                    EventTime = $ts
                    DeltaMinutes = [math]::Round($delta, 1)
                    Summary = (($item | ConvertTo-Json -Compress -Depth 6))
                }
            }
        }
    }

    return @($rows | Sort-Object BsodTime, EventTime)
}

function Write-Report {
    param(
        [array]$BsodEvents,
        [array]$CorrelatedEvents,
        [array]$Suspects,
        [array]$MemoryContext,
        [int]$TopCount
    )

    Write-Section "BSOD events"
    $BsodEvents | Select-Object TimeCreated, Id, ProviderName, BugCheckCode, Hint | Format-Table -AutoSize

    Write-Section "Suspect providers"
    $Suspects | Select-Object -First $TopCount | Format-Table -AutoSize

    Write-Section "Correlated System Error/Critical events"
    $CorrelatedEvents |
        Select-Object BsodTime, EventTime, DeltaSeconds, ProviderName, Id, LevelDisplayName |
        Format-Table -AutoSize

    Write-Section "Driver detail lookup"
    foreach ($suspect in ($Suspects | Select-Object -First $TopCount)) {
        Write-Host ""
        Write-Host "[$($suspect.ProviderName)]" -ForegroundColor Yellow
        Get-DriverDetail -ProviderName $suspect.ProviderName | Format-List
    }

    if ($MemoryContext.Count -gt 0) {
        Write-Section "Memory pressure context (+/- 5m)"
        $MemoryContext | Select-Object BsodTime, EventTime, DeltaMinutes, Summary | Format-List
    }
}

if ($Days -lt 1) { throw "-Days must be >= 1" }
if ($Top -lt 1) { throw "-Top must be >= 1" }
if ($WindowSec -lt 1) { throw "-WindowSec must be >= 1" }

$since = (Get-Date).AddDays(-1 * $Days)
$bsodEvents = @(Get-BsodEvents -Since $since)

if ($bsodEvents.Count -eq 0) {
    $message = "No BSOD events found in the selected window (Days=$Days)"
    Write-Host $message -ForegroundColor Green
    if ($OutputFile) {
        $outPath = if ([System.IO.Path]::IsPathRooted($OutputFile)) { $OutputFile } else { Join-Path $ProjectRoot $OutputFile }
        $outDir = Split-Path -Parent $outPath
        if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
        Set-Content -LiteralPath $outPath -Value $message -Encoding UTF8
    }
    exit 0
}

$correlated = @(Get-CorrelatedEvents -BsodEvents $bsodEvents -WindowSeconds $WindowSec)
$suspects = @(Find-SuspectDrivers -CorrelatedEvents $correlated -CrashCount $bsodEvents.Count)
$memoryContext = @(Get-MemoryPressureContext -BsodEvents $bsodEvents)

if ($OutputFile) {
    $outPath = if ([System.IO.Path]::IsPathRooted($OutputFile)) { $OutputFile } else { Join-Path $ProjectRoot $OutputFile }
    $outDir = Split-Path -Parent $outPath
    if ($outDir -and -not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }
    & {
        Write-Report -BsodEvents $bsodEvents -CorrelatedEvents $correlated -Suspects $suspects -MemoryContext $memoryContext -TopCount $Top
    } *> $outPath
    Write-Host "Report written: $outPath" -ForegroundColor Green
} else {
    Write-Report -BsodEvents $bsodEvents -CorrelatedEvents $correlated -Suspects $suspects -MemoryContext $memoryContext -TopCount $Top
}

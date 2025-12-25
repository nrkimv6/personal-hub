# Monitor Page - Log Viewer Script
# View logs for API server, worker, and frontend in real-time

param(
    [Parameter(Position=0)]
    [ValidateSet("all", "api", "worker", "frontend", "list")]
    [string]$Target = "all",

    [Parameter()]
    [int]$Lines = 50,

    [Parameter()]
    [switch]$Follow,

    [Parameter()]
    [switch]$FromStart,  # Show logs from beginning of file (not just tail)

    [Parameter()]
    [switch]$Dev,  # Use development log directory (logs/dev/)

    [Parameter()]
    [switch]$Help
)

# Set console output encoding to UTF-8 for Korean support
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# Log directory based on mode
if ($Dev) {
    $LogDir = Join-Path $ProjectRoot "logs\dev"
    # Create dev log directory if it doesn't exist
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
} else {
    $LogDir = Join-Path $ProjectRoot "logs"
}

# Show help
if ($Help) {
    Write-Host @"

Monitor Page Log Viewer
=======================

Usage:
    .\logs.ps1 [target] [-Lines N] [-Follow] [-Help]

Targets:
    all      Show API, Worker, and Frontend logs together (default)
    api      Show API server logs only
    worker   Show Worker logs only
    frontend Show Frontend logs only
    list     List available log files

Options:
    -Lines N    Number of lines to show (default: 50)
    -Follow     Follow logs in real-time (like tail -f)
    -Help       Show this help message

Examples:
    .\logs.ps1                  # Show last 50 lines of all logs
    .\logs.ps1 api              # Show API logs only
    .\logs.ps1 worker -Lines 100  # Show last 100 lines of worker logs
    .\logs.ps1 all -Follow      # Follow all logs in real-time

"@
    exit 0
}

# Check log directory
if (-not (Test-Path $LogDir)) {
    Write-Host "[!] Log directory not found: $LogDir" -ForegroundColor Red
    exit 1
}

# Get latest log file function (by filename timestamp, not LastWriteTime)
function Get-LatestLogFile {
    param([string]$Prefix)

    $pattern = Join-Path $LogDir "$Prefix*.log"
    # Sort by Name descending - filenames contain timestamps like api_20251211_094846.log
    $files = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object Name -Descending
    if ($files) {
        return $files[0].FullName
    }
    return $null
}

# List log files
if ($Target -eq "list") {
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Available Log Files" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # API logs
    Write-Host "[API Server Logs]" -ForegroundColor Yellow
    $apiLogs = Get-ChildItem (Join-Path $LogDir "stdout_api_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($apiLogs) {
        foreach ($log in $apiLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""

    # Worker logs
    Write-Host "[Worker Logs]" -ForegroundColor Yellow
    $workerLogs = Get-ChildItem (Join-Path $LogDir "stdout_worker_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($workerLogs) {
        foreach ($log in $workerLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""

    # Frontend logs
    Write-Host "[Frontend Logs]" -ForegroundColor Yellow
    $frontendLogs = Get-ChildItem (Join-Path $LogDir "frontend_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    if ($frontendLogs) {
        foreach ($log in $frontendLogs) {
            $size = "{0:N2} KB" -f ($log.Length / 1KB)
            $date = $log.LastWriteTime.ToString("yyyy-MM-dd HH:mm:ss")
            Write-Host "  $($log.Name) - $size - $date"
        }
    } else {
        Write-Host "  (none)" -ForegroundColor Gray
    }

    Write-Host ""
    exit 0
}

# Get log files (stdout_* prefix is used by run.ps1)
$apiLogFile = Get-LatestLogFile "stdout_api_"
$workerLogFile = Get-LatestLogFile "stdout_worker_"
$frontendLogFile = Get-LatestLogFile "frontend_"

# Check if log files are stale (created more than 1 hour before the latest API log)
function Test-StaleLogFile {
    param([string]$FilePath, [string]$ReferenceFile)

    if (-not $FilePath -or -not $ReferenceFile) { return $false }
    if (-not (Test-Path $FilePath) -or -not (Test-Path $ReferenceFile)) { return $false }

    $fileTime = (Get-Item $FilePath).LastWriteTime
    $refTime = (Get-Item $ReferenceFile).LastWriteTime

    # If the file was last modified more than 1 hour before the reference file, it's stale
    return ($refTime - $fileTime).TotalHours -gt 1
}

# Warn about potentially stale log files
if ($apiLogFile) {
    if ($workerLogFile -and (Test-StaleLogFile $workerLogFile $apiLogFile)) {
        Write-Host "[!] Worker log may be stale (from previous session)" -ForegroundColor Yellow
        $workerLogFile = $null  # Don't show stale logs
    }
    if ($frontendLogFile -and (Test-StaleLogFile $frontendLogFile $apiLogFile)) {
        Write-Host "[!] Frontend log may be stale (from previous session)" -ForegroundColor Yellow
        $frontendLogFile = $null  # Don't show stale logs
    }
}

# Show log content function
function Show-LogContent {
    param(
        [string]$FilePath,
        [string]$Label,
        [ConsoleColor]$Color,
        [int]$TailLines
    )

    if (-not $FilePath -or -not (Test-Path $FilePath)) {
        Write-Host "[$Label] Log file not found" -ForegroundColor Gray
        return
    }

    Write-Host "`n========================================" -ForegroundColor $Color
    Write-Host "  $Label Log" -ForegroundColor $Color
    Write-Host "  File: $(Split-Path $FilePath -Leaf)" -ForegroundColor $Color
    Write-Host "========================================" -ForegroundColor $Color
    Write-Host ""

    # Read last N lines
    $content = Get-Content $FilePath -Tail $TailLines -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($content) {
        foreach ($line in $content) {
            # Color based on log level
            $lineColor = "White"
            if ($line -match "ERROR|CRITICAL") {
                $lineColor = "Red"
            } elseif ($line -match "WARNING") {
                $lineColor = "Yellow"
            } elseif ($line -match "INFO") {
                $lineColor = "Green"
            } elseif ($line -match "DEBUG") {
                $lineColor = "Gray"
            }
            Write-Host $line -ForegroundColor $lineColor
        }
    } else {
        Write-Host "(no content)" -ForegroundColor Gray
    }
}

# Real-time log tail function (single file)
function Start-LogTail {
    param(
        [string]$FilePath,
        [string]$Prefix
    )

    if (-not $FilePath -or -not (Test-Path $FilePath)) {
        Write-Host "[!] Log file not found: $Prefix" -ForegroundColor Red
        return
    }

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Real-time Log: $Prefix" -ForegroundColor Cyan
    Write-Host "  File: $(Split-Path $FilePath -Leaf)" -ForegroundColor Cyan
    Write-Host "  Exit: Ctrl+C" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Use PowerShell Get-Content -Wait
    Get-Content $FilePath -Wait -Tail 10 -Encoding UTF8 | ForEach-Object {
        $line = $_
        $lineColor = "White"
        if ($line -match "ERROR|CRITICAL") {
            $lineColor = "Red"
        } elseif ($line -match "WARNING") {
            $lineColor = "Yellow"
        } elseif ($line -match "INFO") {
            $lineColor = "Green"
        } elseif ($line -match "DEBUG") {
            $lineColor = "Gray"
        }
        Write-Host $line -ForegroundColor $lineColor
    }
}

# Real-time combined log tail (using FileSystemWatcher instead of Start-Job for UTF-8 support)
function Start-CombinedLogTail {
    param(
        [string]$ApiLog,
        [string]$WorkerLog,
        [string]$FrontendLog
    )

    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host "  Real-time Combined Log" -ForegroundColor Cyan
    Write-Host "  Exit: Ctrl+C" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Track file positions
    $filePositions = @{}
    $logFiles = @{}

    if ($ApiLog -and (Test-Path $ApiLog)) {
        $logFiles["API"] = $ApiLog
        $filePositions["API"] = (Get-Item $ApiLog).Length
        # Show last 5 lines initially
        $initLines = Get-Content $ApiLog -Tail 5 -Encoding UTF8 -ErrorAction SilentlyContinue
        foreach ($line in $initLines) {
            Write-Host "[API] $line" -ForegroundColor Cyan
        }
    }

    if ($WorkerLog -and (Test-Path $WorkerLog)) {
        $logFiles["WORKER"] = $WorkerLog
        $filePositions["WORKER"] = (Get-Item $WorkerLog).Length
        # Show last 5 lines initially
        $initLines = Get-Content $WorkerLog -Tail 5 -Encoding UTF8 -ErrorAction SilentlyContinue
        foreach ($line in $initLines) {
            Write-Host "[WORKER] $line" -ForegroundColor Magenta
        }
    }

    if ($FrontendLog -and (Test-Path $FrontendLog)) {
        $logFiles["FRONTEND"] = $FrontendLog
        $filePositions["FRONTEND"] = (Get-Item $FrontendLog).Length
        # Show last 5 lines initially
        $initLines = Get-Content $FrontendLog -Tail 5 -Encoding UTF8 -ErrorAction SilentlyContinue
        foreach ($line in $initLines) {
            Write-Host "[FRONTEND] $line" -ForegroundColor Green
        }
    }

    if ($logFiles.Count -eq 0) {
        Write-Host "[!] No log files to follow." -ForegroundColor Red
        return
    }

    Write-Host "`n--- Following logs... ---`n" -ForegroundColor DarkGray

    try {
        while ($true) {
            foreach ($source in $logFiles.Keys) {
                $filePath = $logFiles[$source]
                $currentSize = (Get-Item $filePath -ErrorAction SilentlyContinue).Length

                if ($currentSize -gt $filePositions[$source]) {
                    # Read new content using StreamReader for proper UTF-8
                    $stream = [System.IO.FileStream]::new($filePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                    $stream.Seek($filePositions[$source], [System.IO.SeekOrigin]::Begin) | Out-Null
                    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)

                    while ($null -ne ($line = $reader.ReadLine())) {
                        # Determine color based on source
                        $sourceColor = switch ($source) {
                            "API" { "Cyan" }
                            "WORKER" { "Magenta" }
                            "FRONTEND" { "Green" }
                            default { "White" }
                        }

                        # Override color for errors/warnings
                        if ($line -match "ERROR|CRITICAL") {
                            $sourceColor = "Red"
                        } elseif ($line -match "WARNING") {
                            $sourceColor = "Yellow"
                        }

                        Write-Host "[$source] $line" -ForegroundColor $sourceColor
                    }

                    $filePositions[$source] = $stream.Position
                    $reader.Close()
                    $stream.Close()
                }
            }
            Start-Sleep -Milliseconds 200
        }
    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }
}

# Main logic
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Log Viewer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Real-time follow mode
if ($Follow) {
    switch ($Target) {
        "api" {
            Start-LogTail -FilePath $apiLogFile -Prefix "API"
        }
        "worker" {
            Start-LogTail -FilePath $workerLogFile -Prefix "Worker"
        }
        "frontend" {
            Start-LogTail -FilePath $frontendLogFile -Prefix "Frontend"
        }
        default {
            Start-CombinedLogTail -ApiLog $apiLogFile -WorkerLog $workerLogFile -FrontendLog $frontendLogFile
        }
    }
} else {
    # Static log display
    switch ($Target) {
        "api" {
            Show-LogContent -FilePath $apiLogFile -Label "API Server" -Color Cyan -TailLines $Lines
        }
        "worker" {
            Show-LogContent -FilePath $workerLogFile -Label "Worker" -Color Magenta -TailLines $Lines
        }
        "frontend" {
            Show-LogContent -FilePath $frontendLogFile -Label "Frontend" -Color Green -TailLines $Lines
        }
        default {
            Show-LogContent -FilePath $apiLogFile -Label "API Server" -Color Cyan -TailLines $Lines
            Show-LogContent -FilePath $workerLogFile -Label "Worker" -Color Magenta -TailLines $Lines
            Show-LogContent -FilePath $frontendLogFile -Label "Frontend" -Color Green -TailLines $Lines
        }
    }
}

Write-Host ""

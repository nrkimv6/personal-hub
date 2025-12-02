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
    [switch]$Help
)

# Set console output encoding to UTF-8 for Korean support
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"

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

# Get latest log file function
function Get-LatestLogFile {
    param([string]$Prefix)

    $pattern = Join-Path $LogDir "$Prefix*.log"
    $files = Get-ChildItem $pattern -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
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
    $apiLogs = Get-ChildItem (Join-Path $LogDir "api_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
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
    $workerLogs = Get-ChildItem (Join-Path $LogDir "worker_*.log") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
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

# Get log files
$apiLogFile = Get-LatestLogFile "api_"
$workerLogFile = Get-LatestLogFile "worker_"
$frontendLogFile = Get-LatestLogFile "frontend_"

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

# Real-time combined log tail
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

    # Create jobs to monitor file changes
    $jobs = @()

    if ($ApiLog -and (Test-Path $ApiLog)) {
        $job = Start-Job -ScriptBlock {
            param($logPath)
            Get-Content $logPath -Wait -Tail 5 -Encoding UTF8 | ForEach-Object {
                "[API] $_"
            }
        } -ArgumentList $ApiLog
        $jobs += $job
    }

    if ($WorkerLog -and (Test-Path $WorkerLog)) {
        $job = Start-Job -ScriptBlock {
            param($logPath)
            Get-Content $logPath -Wait -Tail 5 -Encoding UTF8 | ForEach-Object {
                "[WORKER] $_"
            }
        } -ArgumentList $WorkerLog
        $jobs += $job
    }

    if ($FrontendLog -and (Test-Path $FrontendLog)) {
        $job = Start-Job -ScriptBlock {
            param($logPath)
            Get-Content $logPath -Wait -Tail 5 -Encoding UTF8 | ForEach-Object {
                "[FRONTEND] $_"
            }
        } -ArgumentList $FrontendLog
        $jobs += $job
    }

    if ($jobs.Count -eq 0) {
        Write-Host "[!] No log files to follow." -ForegroundColor Red
        return
    }

    try {
        while ($true) {
            foreach ($job in $jobs) {
                $output = Receive-Job -Job $job -ErrorAction SilentlyContinue
                if ($output) {
                    foreach ($line in $output) {
                        $lineColor = "White"
                        if ($line -match "ERROR|CRITICAL|error") {
                            $lineColor = "Red"
                        } elseif ($line -match "WARNING|warn") {
                            $lineColor = "Yellow"
                        } elseif ($line -match "INFO") {
                            $lineColor = "Green"
                        } elseif ($line -match "DEBUG") {
                            $lineColor = "Gray"
                        }

                        # Color by source
                        if ($line -match "^\[API\]") {
                            Write-Host $line -ForegroundColor Cyan
                        } elseif ($line -match "^\[WORKER\]") {
                            Write-Host $line -ForegroundColor Magenta
                        } elseif ($line -match "^\[FRONTEND\]") {
                            Write-Host $line -ForegroundColor Green
                        } else {
                            Write-Host $line -ForegroundColor $lineColor
                        }
                    }
                }
            }
            Start-Sleep -Milliseconds 100
        }
    } finally {
        # Cleanup jobs
        $jobs | Stop-Job -ErrorAction SilentlyContinue
        $jobs | Remove-Job -Force -ErrorAction SilentlyContinue
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

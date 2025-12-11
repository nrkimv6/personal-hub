# Monitor Page - Integrated Run Script
# Starts all processes, shows logs, and stops on exit (Ctrl+C)

param(
    [switch]$Dev,        # Pass -Dev to start.ps1 for frontend foreground mode
    [switch]$SkipWorker  # Skip worker (run it separately in PyCharm debugger)
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page - Integrated Runner" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Start all processes (API, Worker, Frontend)"
Write-Host "  2. Show real-time logs"
Write-Host "  3. Stop all processes when you press Ctrl+C"
Write-Host ""

# Register cleanup on script exit
$stopScript = Join-Path $ScriptDir "stop.ps1"

# Use Register-EngineEvent for Ctrl+C handling
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Write-Host "`n`n[!] Shutting down..." -ForegroundColor Yellow
}

try {
    # Step 1: Start processes
    Write-Host "[Step 1] Starting processes..." -ForegroundColor Cyan
    Write-Host "----------------------------------------"

    $startScript = Join-Path $ScriptDir "start.ps1"

    if ($Dev) {
        # In Dev mode: API/Worker background + Frontend foreground + show all logs
        Write-Host "[!] Dev mode: Frontend in foreground + backend logs" -ForegroundColor Yellow
        Write-Host ""

        # Start API and Worker only (not frontend)
        $env:SKIP_FRONTEND = "true"
        if ($SkipWorker) {
            $env:SKIP_WORKER = "true"
        }
        & $startScript
        $env:SKIP_FRONTEND = $null
        $env:SKIP_WORKER = $null

        # Wait for log files to be created
        Start-Sleep -Seconds 2

        # Find the most recent log files by filename (contains timestamp like worker_20251211_094846.log)
        # Using Name sort instead of LastWriteTime because old log files may be updated when processes stop
        $LogDir = Join-Path $ProjectRoot "logs"

        $apiLog = Get-ChildItem -Path $LogDir -Filter "api_*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1

        $workerLog = Get-ChildItem -Path $LogDir -Filter "worker_*.log" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending | Select-Object -First 1

        Write-Host ""
        Write-Host "[Step 2] Starting frontend + tailing backend logs..." -ForegroundColor Cyan
        Write-Host "----------------------------------------"

        # Show existing log content first
        if ($apiLog) {
            Write-Host "[API] === Log from start ===" -ForegroundColor Cyan
            Get-Content $apiLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "[API] $_" -ForegroundColor Cyan
            }
        }
        if ($workerLog) {
            Write-Host "[WORKER] === Log from start ===" -ForegroundColor Magenta
            Get-Content $workerLog.FullName -Encoding UTF8 -ErrorAction SilentlyContinue | ForEach-Object {
                Write-Host "[WORKER] $_" -ForegroundColor Magenta
            }
        }

        Write-Host ""
        Write-Host "--- Frontend starting (Ctrl+C to stop all) ---" -ForegroundColor Yellow
        Write-Host ""

        # Track log file positions for tailing
        $apiPos = if ($apiLog) { (Get-Item $apiLog.FullName).Length } else { 0 }
        $workerPos = if ($workerLog) { (Get-Item $workerLog.FullName).Length } else { 0 }

        # Start frontend in background (so we can tail logs)
        $FrontendDir = Join-Path $ProjectRoot "frontend"
        $frontendLogFile = Join-Path $LogDir "frontend_dev.log"

        # Start frontend and capture its actual PID via port
        $FrontendPidFile = Join-Path $ProjectRoot ".pids\frontend.pid"
        "DEV_MODE" | Out-File $FrontendPidFile -Encoding ascii
        $frontendPos = 0

        # Start frontend in background
        Start-Process -FilePath "cmd.exe" `
            -ArgumentList "/c", "cd /d `"$FrontendDir`" && npm run dev -- --host --port 5173 > `"$frontendLogFile`" 2>&1" `
            -WindowStyle Hidden

        # Wait for vite to start (check port with timeout)
        Write-Host "[*] Waiting for frontend to start on port 5173..." -ForegroundColor Gray
        $maxWait = 30  # 30 seconds max
        $waited = 0
        while ($waited -lt $maxWait) {
            $conn = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
            if ($conn) {
                Write-Host "[+] Frontend is running on port 5173" -ForegroundColor Green
                break
            }
            Start-Sleep -Seconds 1
            $waited++

            # Also tail logs while waiting
            if (Test-Path $frontendLogFile) {
                $currentSize = (Get-Item $frontendLogFile).Length
                if ($currentSize -gt $frontendPos) {
                    $stream = [System.IO.FileStream]::new($frontendLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                    $stream.Seek($frontendPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                    $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                    while ($null -ne ($line = $reader.ReadLine())) {
                        Write-Host "[FRONTEND] $line" -ForegroundColor Green
                    }
                    $frontendPos = $stream.Position
                    $reader.Close()
                    $stream.Close()
                }
            }
        }

        if ($waited -ge $maxWait) {
            Write-Host "[!] Frontend failed to start within ${maxWait}s" -ForegroundColor Red
            throw "Frontend startup timeout"
        }

        try {
            # Tail all logs while frontend runs (check port)
            while ($true) {
                # Check if frontend is still running via port
                $conn = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
                if (-not $conn) {
                    Write-Host "[!] Frontend stopped" -ForegroundColor Yellow
                    break
                }
                # Tail API log
                if ($apiLog -and (Test-Path $apiLog.FullName)) {
                    $currentSize = (Get-Item $apiLog.FullName).Length
                    if ($currentSize -gt $apiPos) {
                        $stream = [System.IO.FileStream]::new($apiLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($apiPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[API] $line" -ForegroundColor Cyan
                        }
                        $apiPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Worker log
                if ($workerLog -and (Test-Path $workerLog.FullName)) {
                    $currentSize = (Get-Item $workerLog.FullName).Length
                    if ($currentSize -gt $workerPos) {
                        $stream = [System.IO.FileStream]::new($workerLog.FullName, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($workerPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[WORKER] $line" -ForegroundColor Magenta
                        }
                        $workerPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                # Tail Frontend log
                if (Test-Path $frontendLogFile) {
                    $currentSize = (Get-Item $frontendLogFile).Length
                    if ($currentSize -gt $frontendPos) {
                        $stream = [System.IO.FileStream]::new($frontendLogFile, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
                        $stream.Seek($frontendPos, [System.IO.SeekOrigin]::Begin) | Out-Null
                        $reader = [System.IO.StreamReader]::new($stream, [System.Text.Encoding]::UTF8)
                        while ($null -ne ($line = $reader.ReadLine())) {
                            Write-Host "[FRONTEND] $line" -ForegroundColor Green
                        }
                        $frontendPos = $stream.Position
                        $reader.Close()
                        $stream.Close()
                    }
                }

                Start-Sleep -Milliseconds 200
            }
        } finally {
            # Cleanup - kill frontend via port
            $conn = Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
            if ($conn) {
                $pids = $conn | Select-Object -ExpandProperty OwningProcess -Unique
                foreach ($pid in $pids) {
                    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                }
            }
            Remove-Item $FrontendPidFile -Force -ErrorAction SilentlyContinue
        }
    } else {
        # Normal mode: all background, then follow logs
        & $startScript

        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
            Write-Host "[!] Start script returned non-zero exit code" -ForegroundColor Yellow
        }

        # Step 2: Show logs (in follow mode)
        Write-Host ""
        Write-Host "[Step 2] Following logs (Ctrl+C to stop)..." -ForegroundColor Cyan
        Write-Host "----------------------------------------"

        $logsScript = Join-Path $ScriptDir "logs.ps1"
        & $logsScript -Follow
    }

} finally {
    # Step 3: Stop all processes on exit
    Write-Host ""
    Write-Host ""
    Write-Host "[Step 3] Stopping all processes..." -ForegroundColor Yellow
    Write-Host "----------------------------------------"

    & $stopScript -Force

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Run complete" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
}

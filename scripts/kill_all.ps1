# Kill ALL monitor-page processes (Python + Chrome + LOCK files)
# Use this when everything is messed up

Write-Host "=== KILLING ALL MONITOR-PAGE PROCESSES ===" -ForegroundColor Red
Write-Host ""

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# 1. Kill ALL Python processes related to monitor-page
Write-Host "[1] Killing Python processes..." -ForegroundColor Cyan
$pythonProcs = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue
$pythonKilled = 0
foreach ($proc in $pythonProcs) {
    $cmd = $proc.CommandLine
    if ($cmd -and ($cmd -like "*monitor-page*" -or $cmd -like "*app.worker*" -or $cmd -like "*instagram_worker*" -or $cmd -like "*llm_worker*" -or $cmd -like "*uvicorn*" -or $cmd -like "*app.main*")) {
        Write-Host "  Killing PID $($proc.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        $pythonKilled++
    }
}
Write-Host "  -> Killed $pythonKilled Python processes" -ForegroundColor Green

# 2. Kill ALL Playwright Chrome processes
Write-Host ""
Write-Host "[2] Killing Playwright Chrome processes..." -ForegroundColor Cyan
$chromeProcs = Get-Process -Name "chrome" -ErrorAction SilentlyContinue
$chromeKilled = 0
foreach ($proc in $chromeProcs) {
    try {
        $procPath = $proc.Path
        if ($procPath -and $procPath -like "*ms-playwright*") {
            Write-Host "  Killing PID $($proc.Id)" -ForegroundColor Yellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $chromeKilled++
        }
    } catch {}
}
Write-Host "  -> Killed $chromeKilled Chrome processes" -ForegroundColor Green

# 3. Wait for processes to terminate
Write-Host ""
Write-Host "[3] Waiting for processes to terminate..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

# 4. Clean LOCK files
Write-Host ""
Write-Host "[4] Cleaning LOCK files..." -ForegroundColor Cyan
$browserProfilesPath = Join-Path $ProjectRoot "data\browser_profiles"
if (Test-Path $browserProfilesPath) {
    $lockFiles = Get-ChildItem -Path $browserProfilesPath -Filter "LOCK" -Recurse -ErrorAction SilentlyContinue
    $lockCount = 0
    foreach ($lock in $lockFiles) {
        Remove-Item $lock.FullName -Force -ErrorAction SilentlyContinue
        $lockCount++
    }
    Write-Host "  -> Deleted $lockCount LOCK files" -ForegroundColor Green
}

# 5. Clean PID files
Write-Host ""
Write-Host "[5] Cleaning PID files..." -ForegroundColor Cyan
$pidDir = Join-Path $ProjectRoot ".pids"
if (Test-Path $pidDir) {
    Get-ChildItem -Path $pidDir -Filter "*.pid" | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "  -> PID files cleaned" -ForegroundColor Green
}

# 6. Final check
Write-Host ""
Write-Host "[6] Final check..." -ForegroundColor Cyan
$remainingPython = (Get-Process python -ErrorAction SilentlyContinue).Count
$remainingChrome = (Get-Process chrome -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -like "*ms-playwright*" } catch { $false }
}).Count
Write-Host "  Remaining Python: $remainingPython" -ForegroundColor $(if ($remainingPython -gt 10) { "Yellow" } else { "Green" })
Write-Host "  Remaining Playwright Chrome: $remainingChrome" -ForegroundColor $(if ($remainingChrome -gt 0) { "Yellow" } else { "Green" })

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Green
Write-Host "Now run: .\scripts\run.ps1 -Dev" -ForegroundColor Cyan

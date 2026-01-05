# Monitor Page - 시작 프로그램 등록/해제
# 부팅 후 자동으로 서비스 로그 창을 엽니다.
# -IncludeWorkers 옵션으로 브라우저 워커도 등록할 수 있습니다.
# -IncludeApiWatchdog 옵션으로 API Watchdog도 등록할 수 있습니다.
#
# 사용법:
#   .\startup-install.ps1 -Action install                       # 로그 뷰어만 등록
#   .\startup-install.ps1 -Action install -IncludeWorkers       # 로그 뷰어 + 브라우저 워커 등록
#   .\startup-install.ps1 -Action install -IncludeApiWatchdog   # 로그 뷰어 + API Watchdog 등록
#   .\startup-install.ps1 -Action install -IncludeWorkers -IncludeApiWatchdog  # 전체 등록
#   .\startup-install.ps1 -Action uninstall                     # 시작 프로그램 해제
#   .\startup-install.ps1 -Action status                        # 상태 확인

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("install", "uninstall", "status")]
    [string]$Action,

    [switch]$IncludeWorkers,      # 브라우저 워커 시작 프로그램 포함
    [switch]$IncludeApiWatchdog   # API Watchdog 시작 프로그램 포함
)

$ShortcutName = "MonitorPage-Logs.lnk"
$ShortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\$ShortcutName"
$WorkerShortcutName = "MonitorPage-BrowserWorkers.lnk"
$WorkerShortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\$WorkerShortcutName"
$ApiWatchdogShortcutName = "MonitorPage-APIWatchdog.lnk"
$ApiWatchdogShortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\$ApiWatchdogShortcutName"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$StartupScript = Join-Path $ScriptDir "startup-logs.ps1"
$WorkerStartupScript = Join-Path $ScriptDir "startup-browser-workers.ps1"
$ApiWatchdogStartupScript = Join-Path $ScriptDir "startup-api-watchdog.ps1"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Startup Registration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

switch ($Action) {
    "install" {
        # 로그 뷰어 바로가기 생성
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = "powershell.exe"
        $Shortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartupScript`""
        $Shortcut.WorkingDirectory = $ProjectRoot
        $Shortcut.Description = "Monitor Page - Auto open service logs on startup"
        $Shortcut.Save()

        Write-Host "[+] Log viewer startup registered" -ForegroundColor Green
        Write-Host "    Location: $ShortcutPath" -ForegroundColor Gray

        # 브라우저 워커 바로가기 생성 (옵션)
        if ($IncludeWorkers) {
            $WorkerShortcut = $WshShell.CreateShortcut($WorkerShortcutPath)
            $WorkerShortcut.TargetPath = "powershell.exe"
            $WorkerShortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WorkerStartupScript`""
            $WorkerShortcut.WorkingDirectory = $ProjectRoot
            $WorkerShortcut.Description = "Monitor Page - Auto start browser workers on login"
            $WorkerShortcut.Save()

            Write-Host "[+] Browser workers startup registered" -ForegroundColor Green
            Write-Host "    Location: $WorkerShortcutPath" -ForegroundColor Gray
        }

        # API Watchdog 바로가기 생성 (옵션)
        if ($IncludeApiWatchdog) {
            $ApiWatchdogShortcut = $WshShell.CreateShortcut($ApiWatchdogShortcutPath)
            $ApiWatchdogShortcut.TargetPath = "powershell.exe"
            $ApiWatchdogShortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ApiWatchdogStartupScript`""
            $ApiWatchdogShortcut.WorkingDirectory = $ProjectRoot
            $ApiWatchdogShortcut.Description = "Monitor Page - API Watchdog (hang detection + staged recovery)"
            $ApiWatchdogShortcut.Save()

            Write-Host "[+] API Watchdog startup registered" -ForegroundColor Green
            Write-Host "    Location: $ApiWatchdogShortcutPath" -ForegroundColor Gray
        }

        Write-Host ""
        Write-Host "On next login:" -ForegroundColor Yellow
        Write-Host "  1. Wait 15 seconds - Log viewer window opens"
        if ($IncludeWorkers) {
            Write-Host "  2. Wait 20 seconds - Browser workers start"
        }
        if ($IncludeApiWatchdog) {
            Write-Host "  3. Wait 30 seconds - API Watchdog starts (hang detection)"
        }
        Write-Host ""
    }

    "uninstall" {
        $removed = $false

        if (Test-Path $ShortcutPath) {
            Remove-Item $ShortcutPath -Force
            Write-Host "[+] Log viewer startup removed" -ForegroundColor Green
            $removed = $true
        } else {
            Write-Host "[!] Log viewer startup not registered" -ForegroundColor Yellow
        }

        if ($IncludeWorkers) {
            if (Test-Path $WorkerShortcutPath) {
                Remove-Item $WorkerShortcutPath -Force
                Write-Host "[+] Browser workers startup removed" -ForegroundColor Green
                $removed = $true
            } else {
                Write-Host "[!] Browser workers startup not registered" -ForegroundColor Yellow
            }
        }

        if ($IncludeApiWatchdog) {
            if (Test-Path $ApiWatchdogShortcutPath) {
                Remove-Item $ApiWatchdogShortcutPath -Force
                Write-Host "[+] API Watchdog startup removed" -ForegroundColor Green
                $removed = $true
            } else {
                Write-Host "[!] API Watchdog startup not registered" -ForegroundColor Yellow
            }
        }
    }

    "status" {
        Write-Host "Startup Programs:" -ForegroundColor Cyan

        # 로그 뷰어
        Write-Host "  Log Viewer:" -ForegroundColor White
        if (Test-Path $ShortcutPath) {
            Write-Host "    [+] Registered" -ForegroundColor Green
        } else {
            Write-Host "    [-] Not registered" -ForegroundColor Yellow
        }

        # 브라우저 워커
        Write-Host "  Browser Workers:" -ForegroundColor White
        if (Test-Path $WorkerShortcutPath) {
            Write-Host "    [+] Registered" -ForegroundColor Green
        } else {
            Write-Host "    [-] Not registered" -ForegroundColor Yellow
        }

        # API Watchdog
        Write-Host "  API Watchdog:" -ForegroundColor White
        if (Test-Path $ApiWatchdogShortcutPath) {
            Write-Host "    [+] Registered" -ForegroundColor Green
        } else {
            Write-Host "    [-] Not registered" -ForegroundColor Yellow
        }
        Write-Host ""

        # 브라우저 워커 프로세스 상태
        Write-Host "Browser Workers Status:" -ForegroundColor Cyan
        $PidDir = Join-Path $ProjectRoot ".pids"
        $watchdogPid = Join-Path $PidDir "watchdog_dev.pid"
        $igWatchdogPid = Join-Path $PidDir "instagram_watchdog_dev.pid"

        Write-Host "  Monitor Worker Watchdog:" -ForegroundColor White
        if ((Test-Path $watchdogPid) -and (Get-Process -Id (Get-Content $watchdogPid -ErrorAction SilentlyContinue) -ErrorAction SilentlyContinue)) {
            $savedPid = Get-Content $watchdogPid
            Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
        } else {
            Write-Host "    [-] Not running" -ForegroundColor Yellow
        }

        Write-Host "  Instagram Worker Watchdog:" -ForegroundColor White
        if ((Test-Path $igWatchdogPid) -and (Get-Process -Id (Get-Content $igWatchdogPid -ErrorAction SilentlyContinue) -ErrorAction SilentlyContinue)) {
            $savedPid = Get-Content $igWatchdogPid
            Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
        } else {
            Write-Host "    [-] Not running" -ForegroundColor Yellow
        }

        $apiWatchdogPid = Join-Path $PidDir "api_watchdog_dev.pid"
        Write-Host "  API Watchdog:" -ForegroundColor White
        if ((Test-Path $apiWatchdogPid) -and (Get-Process -Id (Get-Content $apiWatchdogPid -ErrorAction SilentlyContinue) -ErrorAction SilentlyContinue)) {
            $savedPid = Get-Content $apiWatchdogPid
            Write-Host "    [+] Running (PID: $savedPid)" -ForegroundColor Green
        } else {
            Write-Host "    [-] Not running" -ForegroundColor Yellow
        }
        Write-Host ""

        # 서비스 상태도 함께 표시
        Write-Host "Windows Services:" -ForegroundColor Cyan
        $services = @("MonitorPage", "MonitorPage-Dev", "cloudflared")
        foreach ($svcName in $services) {
            $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
            if ($svc) {
                $color = if ($svc.Status -eq "Running") { "Green" } else { "Yellow" }
                Write-Host "  $svcName : $($svc.Status)" -ForegroundColor $color
            } else {
                Write-Host "  $svcName : Not installed" -ForegroundColor Gray
            }
        }
    }
}

Write-Host ""

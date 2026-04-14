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

function Get-ProjectRoot {
    param([string]$CurrentScriptDir)

    $normalized = $CurrentScriptDir.Trim().Replace('/', '\')
    if ($normalized -match '\\\.worktrees\\') {
        return Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $CurrentScriptDir)))
    }

    return Split-Path -Parent (Split-Path -Parent $CurrentScriptDir)
}

$ProjectRoot = Get-ProjectRoot -CurrentScriptDir $ScriptDir
$StartupScript = Join-Path $ProjectRoot "scripts\logs\startup-logs.ps1"
$WorkerStartupScript = Join-Path $ProjectRoot "scripts\setup\startup-browser-workers.ps1"
$LegacyWorkerStartupScript = Join-Path $ProjectRoot "scripts\startup-browser-workers.ps1"
$ApiWatchdogStartupScript = Join-Path $ProjectRoot "scripts\watchdogs\startup-api-watchdog.ps1"

function Normalize-ShortcutPath {
    param(
        [string]$Path,
        [string]$WorkingDirectory
    )

    if ([string]::IsNullOrWhiteSpace($Path)) {
        return $null
    }

    $candidate = $Path.Trim().Trim('"').Replace('/', '\')

    try {
        if ([System.IO.Path]::IsPathRooted($candidate)) {
            return ([System.IO.Path]::GetFullPath($candidate)).TrimEnd('\')
        }

        if (-not [string]::IsNullOrWhiteSpace($WorkingDirectory)) {
            $base = $WorkingDirectory.Trim().Trim('"').Replace('/', '\')
            if ([System.IO.Path]::IsPathRooted($base)) {
                return ([System.IO.Path]::GetFullPath((Join-Path $base $candidate))).TrimEnd('\')
            }
        }

        return ([System.IO.Path]::GetFullPath($candidate)).TrimEnd('\')
    } catch {
        return $candidate
    }
}

function Get-ShortcutInfo {
    param([string]$ShortcutPath)

    if (-not (Test-Path -LiteralPath $ShortcutPath)) {
        return $null
    }

    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)

        return [pscustomobject]@{
            Path = $ShortcutPath
            TargetPath = $Shortcut.TargetPath
            Arguments = $Shortcut.Arguments
            WorkingDirectory = $Shortcut.WorkingDirectory
            Description = $Shortcut.Description
        }
    } catch {
        return $null
    }
}

function Get-ShortcutFileArgumentPath {
    param(
        [string]$Arguments,
        [string]$WorkingDirectory
    )

    if ([string]::IsNullOrWhiteSpace($Arguments)) {
        return $null
    }

    $match = [regex]::Match($Arguments, '(?i)(?:^|\s)-File\s+(?:"([^"]+)"|(\S+))')
    if (-not $match.Success) {
        return $null
    }

    $value = if ($match.Groups[1].Success) { $match.Groups[1].Value } else { $match.Groups[2].Value }
    return Normalize-ShortcutPath -Path $value -WorkingDirectory $WorkingDirectory
}

function Get-ShortcutPathStatus {
    param(
        $ShortcutInfo,
        [string]$ExpectedScriptPath,
        [string]$LegacyScriptPath
    )

    $expectedPath = Normalize-ShortcutPath -Path $ExpectedScriptPath
    $legacyPath = Normalize-ShortcutPath -Path $LegacyScriptPath

    if (-not $ShortcutInfo) {
        return [pscustomobject]@{
            Status = "missing"
            ShortcutPath = $null
            TargetPath = $null
            Arguments = $null
            WorkingDirectory = $null
            ScriptPath = $null
            ScriptPathExists = $false
            ExpectedScriptPath = $expectedPath
            LegacyScriptPath = $legacyPath
            Reason = "shortcut missing"
        }
    }

    $scriptPath = Get-ShortcutFileArgumentPath -Arguments $ShortcutInfo.Arguments -WorkingDirectory $ShortcutInfo.WorkingDirectory
    $scriptPathExists = $false
    if (-not [string]::IsNullOrWhiteSpace($scriptPath)) {
        $scriptPathExists = Test-Path -LiteralPath $scriptPath
    }

    $status = "stale"
    $reason = "unexpected script path"

    if ([string]::IsNullOrWhiteSpace($scriptPath)) {
        $reason = "missing -File argument"
    } elseif (-not $scriptPathExists) {
        $reason = "script path missing"
    } elseif ((Normalize-ShortcutPath -Path $scriptPath) -ieq $expectedPath) {
        $status = "registered"
        $reason = "matches expected script path"
    } elseif ((Normalize-ShortcutPath -Path $scriptPath) -ieq $legacyPath) {
        $reason = "legacy script path"
    }

    return [pscustomobject]@{
        Status = $status
        ShortcutPath = $ShortcutInfo.Path
        TargetPath = $ShortcutInfo.TargetPath
        Arguments = $ShortcutInfo.Arguments
        WorkingDirectory = $ShortcutInfo.WorkingDirectory
        ScriptPath = $scriptPath
        ScriptPathExists = $scriptPathExists
        ExpectedScriptPath = $expectedPath
        LegacyScriptPath = $legacyPath
        Reason = $reason
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Startup Registration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

switch ($Action) {
    "install" {
        $VenvScripts = Join-Path $ProjectRoot ".venv\Scripts"
        
        # Alias exe 경로 확인 및 fallback
        $ExeLogs = Join-Path $VenvScripts "monitorpage-logs.exe"
        if (-not (Test-Path $ExeLogs)) { $ExeLogs = "powershell.exe" }
        
        $ExeStartup = Join-Path $VenvScripts "monitorpage-startup.exe"
        if (-not (Test-Path $ExeStartup)) { $ExeStartup = "powershell.exe" }
        
        $ExeApiWatchdog = Join-Path $VenvScripts "monitorpage-apiwatchdog.exe"
        if (-not (Test-Path $ExeApiWatchdog)) { $ExeApiWatchdog = "powershell.exe" }
        $ExistingWorkerShortcut = Get-ShortcutInfo -ShortcutPath $WorkerShortcutPath
        $WorkerShortcutStatus = Get-ShortcutPathStatus `
            -ShortcutInfo $ExistingWorkerShortcut `
            -ExpectedScriptPath $WorkerStartupScript `
            -LegacyScriptPath $LegacyWorkerStartupScript

        # 로그 뷰어 바로가기 생성
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $ExeLogs
        $Shortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartupScript`""
        $Shortcut.WorkingDirectory = $ProjectRoot
        $Shortcut.Description = "Monitor Page - Auto open service logs on startup"
        $Shortcut.Save()

        Write-Host "[+] Log viewer startup registered" -ForegroundColor Green
        Write-Host "    Location: $ShortcutPath" -ForegroundColor Gray
        Write-Host "    Target:   $ExeLogs" -ForegroundColor Gray

        # 브라우저 워커 바로가기 생성 (옵션)
        if ($IncludeWorkers) {
            if ($WorkerShortcutStatus.Status -eq "stale") {
                Write-Host "[!] Re-registering stale browser workers shortcut" -ForegroundColor Yellow
                Write-Host "    Current file: $($WorkerShortcutStatus.ScriptPath)" -ForegroundColor Gray
                Write-Host "    Expected:     $WorkerStartupScript" -ForegroundColor Gray
            } elseif ($WorkerShortcutStatus.Status -eq "registered") {
                Write-Host "[+] Browser workers shortcut already points to the current script; refreshing registration" -ForegroundColor Gray
            } else {
                Write-Host "[!] Browser workers startup not registered yet; creating shortcut" -ForegroundColor Yellow
            }

            $WorkerShortcut = $WshShell.CreateShortcut($WorkerShortcutPath)
            $WorkerShortcut.TargetPath = $ExeStartup
            $WorkerShortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$WorkerStartupScript`""
            $WorkerShortcut.WorkingDirectory = $ProjectRoot
            $WorkerShortcut.Description = "Monitor Page - Auto start browser workers on login"
            $WorkerShortcut.Save()

            Write-Host "[+] Browser workers startup registered" -ForegroundColor Green
            Write-Host "    Location: $WorkerShortcutPath" -ForegroundColor Gray
            Write-Host "    Target:   $ExeStartup" -ForegroundColor Gray
        }

        # API Watchdog Task Scheduler 등록 (옵션) — 관리자 권한 필요
        if ($IncludeApiWatchdog) {
            # 잔존 시작 프로그램 바로가기 자동 정리
            if (Test-Path $ApiWatchdogShortcutPath) {
                Remove-Item $ApiWatchdogShortcutPath -Force
                Write-Host "[!] Removed legacy startup shortcut: $ApiWatchdogShortcutName" -ForegroundColor Yellow
            }

            $TaskName = "MonitorPage-APIWatchdog"

            # 기존 태스크 제거 후 재등록
            $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            if ($existingTask) {
                Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
                Write-Host "[!] Removed existing Task Scheduler entry: $TaskName" -ForegroundColor Yellow
            }

            # Action: monitorpage-apiwatchdog.exe (또는 powershell.exe fallback)
            $TaskAction = New-ScheduledTaskAction `
                -Execute $ExeApiWatchdog `
                -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ApiWatchdogStartupScript`"" `
                -WorkingDirectory $ProjectRoot

            # Trigger: AtLogOn + 30초 지연
            $TaskTrigger = New-ScheduledTaskTrigger -AtLogOn
            $TaskTrigger.Delay = "PT30S"

            # Principal: 현재 사용자, RunLevel Highest (관리자 권한)
            $CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
            $TaskPrincipal = New-ScheduledTaskPrincipal `
                -UserId $CurrentUser `
                -RunLevel Highest `
                -LogonType Interactive

            # Settings
            $TaskSettings = New-ScheduledTaskSettingsSet `
                -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
                -MultipleInstances IgnoreNew `
                -StartWhenAvailable

            Register-ScheduledTask `
                -TaskName $TaskName `
                -Action $TaskAction `
                -Trigger $TaskTrigger `
                -Principal $TaskPrincipal `
                -Settings $TaskSettings `
                -Description "Monitor Page - API Watchdog (hang detection + staged recovery, runs as admin)" `
                -Force | Out-Null

            Write-Host "[+] API Watchdog registered in Task Scheduler" -ForegroundColor Green
            Write-Host "    Task:     $TaskName" -ForegroundColor Gray
            Write-Host "    Trigger:  AtLogOn + 30s delay" -ForegroundColor Gray
            Write-Host "    RunLevel: Highest (Administrator)" -ForegroundColor Gray
            Write-Host "    Execute:  $ExeApiWatchdog" -ForegroundColor Gray
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
            $TaskName = "MonitorPage-APIWatchdog"
            $taskExists = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            if ($taskExists) {
                Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
                Write-Host "[+] API Watchdog Task Scheduler entry removed: $TaskName" -ForegroundColor Green
                $removed = $true
            } else {
                Write-Host "[!] API Watchdog Task Scheduler entry not found: $TaskName" -ForegroundColor Yellow
            }
            # 잔존 바로가기도 함께 정리
            if (Test-Path $ApiWatchdogShortcutPath) {
                Remove-Item $ApiWatchdogShortcutPath -Force
                Write-Host "[+] Legacy API Watchdog startup shortcut removed" -ForegroundColor Green
                $removed = $true
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
        $workerShortcutInfo = Get-ShortcutInfo -ShortcutPath $WorkerShortcutPath
        $workerShortcutStatus = Get-ShortcutPathStatus `
            -ShortcutInfo $workerShortcutInfo `
            -ExpectedScriptPath $WorkerStartupScript `
            -LegacyScriptPath $LegacyWorkerStartupScript

        if ($workerShortcutStatus.Status -eq "registered") {
            Write-Host "    [+] Registered" -ForegroundColor Green
            Write-Host "        File: $($workerShortcutStatus.ScriptPath)" -ForegroundColor Gray
        } elseif ($workerShortcutStatus.Status -eq "stale") {
            Write-Host "    [!] Stale path" -ForegroundColor Red
            Write-Host "        Current file: $($workerShortcutStatus.ScriptPath)" -ForegroundColor Gray
            Write-Host "        Expected:     $WorkerStartupScript" -ForegroundColor Gray
            Write-Host "        Target:       $($workerShortcutStatus.TargetPath)" -ForegroundColor Gray
            Write-Host "        Arguments:    $($workerShortcutStatus.Arguments)" -ForegroundColor Gray
        } else {
            Write-Host "    [-] Not registered" -ForegroundColor Yellow
        }

        # API Watchdog (Task Scheduler)
        Write-Host "  API Watchdog (Task Scheduler):" -ForegroundColor White
        $TaskName = "MonitorPage-APIWatchdog"
        $scheduledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($scheduledTask) {
            $taskState = $scheduledTask.State
            $color = if ($taskState -eq "Ready" -or $taskState -eq "Running") { "Green" } else { "Yellow" }
            Write-Host "    [+] Registered (State: $taskState)" -ForegroundColor $color
            $principal = $scheduledTask.Principal
            Write-Host "        RunLevel: $($principal.RunLevel)" -ForegroundColor Gray
        } else {
            Write-Host "    [-] Not registered" -ForegroundColor Yellow
        }
        # 잔존 바로가기 경고
        if (Test-Path $ApiWatchdogShortcutPath) {
            Write-Host "    [!] Legacy shortcut still exists: $ApiWatchdogShortcutPath" -ForegroundColor Red
        }
        Write-Host ""

        # 브라우저 워커 프로세스 상태
        Write-Host "Browser Workers Status:" -ForegroundColor Cyan
        $PidDir = Join-Path $ProjectRoot ".pids"
        $watchdogPid = Join-Path $PidDir "watchdog_admin.pid"
        $igWatchdogPid = Join-Path $PidDir "instagram_watchdog_admin.pid"

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

        $apiWatchdogPid = Join-Path $PidDir "api_watchdog_admin.pid"
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
        $services = @("MonitorPage-Public", "MonitorPage-Admin", "cloudflared")
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

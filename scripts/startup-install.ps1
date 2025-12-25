# Monitor Page - 시작 프로그램 등록/해제
# 부팅 후 자동으로 서비스 로그 창을 엽니다.
#
# 사용법:
#   .\startup-install.ps1 -Action install    # 시작 프로그램 등록
#   .\startup-install.ps1 -Action uninstall  # 시작 프로그램 해제
#   .\startup-install.ps1 -Action status     # 상태 확인

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("install", "uninstall", "status")]
    [string]$Action
)

$ShortcutName = "MonitorPage-Logs.lnk"
$ShortcutPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\$ShortcutName"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$StartupScript = Join-Path $ScriptDir "startup-logs.ps1"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page Startup Registration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

switch ($Action) {
    "install" {
        # 시작 프로그램 바로가기 생성
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = "powershell.exe"
        $Shortcut.Arguments = "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartupScript`""
        $Shortcut.WorkingDirectory = $ProjectRoot
        $Shortcut.Description = "Monitor Page - Auto open service logs on startup"
        $Shortcut.Save()

        Write-Host "[+] Startup program registered" -ForegroundColor Green
        Write-Host ""
        Write-Host "    Location: $ShortcutPath" -ForegroundColor Gray
        Write-Host ""
        Write-Host "    On next login:" -ForegroundColor Yellow
        Write-Host "    1. Wait 15 seconds for services to start"
        Write-Host "    2. Log viewer window opens automatically"
        Write-Host ""
    }

    "uninstall" {
        if (Test-Path $ShortcutPath) {
            Remove-Item $ShortcutPath -Force
            Write-Host "[+] Startup program removed" -ForegroundColor Green
        } else {
            Write-Host "[!] Startup program not registered" -ForegroundColor Yellow
        }
    }

    "status" {
        Write-Host "Startup Program:" -ForegroundColor Cyan
        if (Test-Path $ShortcutPath) {
            Write-Host "  [+] Registered" -ForegroundColor Green
            Write-Host "      Location: $ShortcutPath" -ForegroundColor Gray
        } else {
            Write-Host "  [-] Not registered" -ForegroundColor Yellow
            Write-Host "      Run: .\scripts\startup-install.ps1 -Action install" -ForegroundColor Gray
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

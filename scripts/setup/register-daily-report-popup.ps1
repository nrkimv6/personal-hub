<#
.SYNOPSIS
    Windows 작업 스케줄러에 매일 08:00 일일 보고서 팝업 작업을 등록/갱신한다.

.DESCRIPTION
    가장 최근 logs/daily-reports/*.html 파일을 msedge --app= 모드로 여는
    작업 스케줄러 항목을 멱등하게 등록한다.

    재실행 시 기존 작업을 삭제하고 재등록하므로 설정 변경에도 안전하다.

.PARAMETER TaskName
    등록할 작업 이름. 기본값: MonitorPage_DailyReport

.PARAMETER TriggerHour
    실행 시각 (24h). 기본값: 8 (08:00)

.EXAMPLE
    .\scripts\setup\register-daily-report-popup.ps1
    .\scripts\setup\register-daily-report-popup.ps1 -TriggerHour 9
#>
param(
    [string]$TaskName    = "MonitorPage_DailyReport",
    [int]   $TriggerHour = 8
)

$ProjectRoot    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ReportsDir     = Join-Path $ProjectRoot "logs\daily-reports"
$LauncherScript = Join-Path $ProjectRoot "scripts\setup\_launch_daily_report.ps1"

# 런처 스크립트 자동 생성 (작업 스케줄러는 단순 ps1 실행이 더 안정적)
$LauncherContent = @'
param()
$ReportsDir = "{REPORTS_DIR}"
$Latest = Get-ChildItem -Path $ReportsDir -Filter "*.html" -File -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending |
          Select-Object -First 1
if ($Latest) {
    $AbsPath = $Latest.FullName -replace '\\', '/'
    Start-Process "msedge" --"app=file:///$AbsPath", "--window-size=1200,800"
} else {
    Write-Host "일일 보고서 HTML 파일을 찾을 수 없습니다: $ReportsDir"
}
'@
$LauncherContent = $LauncherContent -replace '\{REPORTS_DIR\}', $ReportsDir
$LauncherContent | Out-File -FilePath $LauncherScript -Encoding UTF8 -Force
Write-Host "런처 스크립트 갱신: $LauncherScript"

# 기존 작업 제거 (멱등)
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "기존 작업 제거: $TaskName"
}

# 트리거: 매일 지정 시각
$Trigger = New-ScheduledTaskTrigger -Daily -At "$($TriggerHour):00"

# 액션: powershell.exe로 런처 스크립트 실행
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$LauncherScript`""

# 현재 사용자로 실행 (로그인 시)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName   $TaskName `
    -Trigger    $Trigger `
    -Action     $Action `
    -Principal  $Principal `
    -Settings   $Settings `
    -Description "Monitor Page 야간 자동 실행 일일 보고서를 08:00에 팝업으로 표시" `
    -Force | Out-Null

Write-Host "작업 등록 완료: $TaskName (매일 $($TriggerHour):00)"
Write-Host ""
Write-Host "확인: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "테스트: Start-ScheduledTask -TaskName '$TaskName'"

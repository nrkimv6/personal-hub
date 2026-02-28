# 일별 유지보수 스크립트
# 작성일: 2025-12-23
#
# 기능:
#   1. 일별 통계 집계 (어제 데이터)
#   2. 오래된 로그 정리
#   3. DB 최적화 (VACUUM)
#
# 사용법:
#   .\scripts\daily_maintenance.ps1
#   .\scripts\daily_maintenance.ps1 -DryRun           # 실제 삭제 안 함
#   .\scripts\daily_maintenance.ps1 -SkipVacuum       # VACUUM 건너뛰기
#   .\scripts\daily_maintenance.ps1 -Date "2025-12-22" # 특정 날짜 지정
#
# Windows 작업 스케줄러 등록 예시:
#   schtasks /create /tn "MonitorPage-DailyMaintenance" /tr "powershell -ExecutionPolicy Bypass -File D:\work\project\tools\monitor-page-multi-profile\scripts\daily_maintenance.ps1" /sc daily /st 00:10

param(
    [switch]$DryRun,
    [switch]$SkipVacuum,
    [string]$Date = "",
    [int]$ProxyUsageDays = 30,
    [int]$ProxyHistoryDays = 90,
    [int]$MonitoringEventsDays = 30
)

$ErrorActionPreference = "Stop"

# 프로젝트 루트 디렉토리
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

# 로그 디렉토리 확인
$LogDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}

$LogFile = Join-Path $LogDir "daily_maintenance.log"
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $LogEntry = "[$Timestamp] [$Level] $Message"
    Write-Host $LogEntry
    Add-Content -Path $LogFile -Value $LogEntry
}

Write-Log "============================================"
Write-Log "일별 유지보수 시작"
Write-Log "============================================"

# cloudflared_err.log 날짜별 분리 (오늘 로그만 원본 유지, 나머지 날짜별 파일 생성)
$SplitCloudflaredScript = Join-Path $PSScriptRoot "split-cloudflared-log.ps1"
if (Test-Path $SplitCloudflaredScript) {
    Write-Log "cloudflared 로그 분리 실행 중..."
    try {
        if ($DryRun) {
            & $SplitCloudflaredScript -DryRun
        } else {
            & $SplitCloudflaredScript
        }
        Write-Log "cloudflared 로그 분리 완료"
    } catch {
        Write-Log "cloudflared 로그 분리 실패 (비치명적): $($_.Exception.Message)" "WARN"
    }
} else {
    Write-Log "split-cloudflared-log.ps1 미발견 — cloudflared 로그 분리 건너뜀" "WARN"
}

# 로그 정리 (Task Scheduler LogCleanup 미등록 시 fallback)
# Task Scheduler에 LogCleanup 태스크가 등록되어 있으면 이 호출은 중복이지만 무해함
$CleanupScript = Join-Path $PSScriptRoot "cleanup-logs.ps1"
if (Test-Path $CleanupScript) {
    Write-Log "로그 파일 정리 실행 중..."
    try {
        if ($DryRun) {
            & $CleanupScript -DryRun
        } else {
            & $CleanupScript
        }
        Write-Log "로그 파일 정리 완료"
    } catch {
        Write-Log "로그 파일 정리 실패 (비치명적): $($_.Exception.Message)" "WARN"
    }
} else {
    Write-Log "cleanup-logs.ps1 미발견 — 로그 정리 건너뜀" "WARN"
}

# API 서버 상태 확인
$ApiUrl = "http://localhost:8000/api/v1/system/health"
try {
    $HealthCheck = Invoke-RestMethod -Uri $ApiUrl -Method Get -TimeoutSec 5
    Write-Log "API 서버 연결 확인: OK"
} catch {
    Write-Log "API 서버에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요." "ERROR"
    exit 1
}

# 유지보수 API 호출
$MaintenanceUrl = "http://localhost:8000/api/v1/maintenance/daily"

$QueryParams = @(
    "proxy_usage_days=$ProxyUsageDays",
    "proxy_history_days=$ProxyHistoryDays",
    "monitoring_events_days=$MonitoringEventsDays"
)

if ($DryRun) {
    $QueryParams += "dry_run=true"
    Write-Log "DRY RUN 모드 - 실제 삭제 없음" "WARN"
}

if ($SkipVacuum) {
    $QueryParams += "run_vacuum=false"
    Write-Log "VACUUM 건너뛰기" "WARN"
}

if ($Date) {
    $QueryParams += "target_date=$Date"
    Write-Log "지정 날짜: $Date"
}

$FullUrl = "$MaintenanceUrl`?" + ($QueryParams -join "&")

Write-Log "유지보수 API 호출 중..."
Write-Log "URL: $FullUrl"

try {
    $StartTime = Get-Date
    $Response = Invoke-RestMethod -Uri $FullUrl -Method Post -TimeoutSec 600
    $EndTime = Get-Date
    $Duration = ($EndTime - $StartTime).TotalSeconds

    if ($Response.success) {
        Write-Log "유지보수 완료 (소요시간: ${Duration}초)"
        Write-Log "  - 프록시 통계 집계: $($Response.proxy_stats_aggregated)건"
        Write-Log "  - 모니터링 통계 집계: $($Response.monitoring_stats_aggregated)건"
        Write-Log "  - proxy_usage_logs 삭제: $($Response.proxy_usage_logs_deleted)건"
        Write-Log "  - proxy_check_history 삭제: $($Response.proxy_check_history_deleted)건"
        Write-Log "  - monitoring_events 삭제: $($Response.monitoring_events_deleted)건"
        Write-Log "  - VACUUM 실행: $($Response.vacuum_executed)"
    } else {
        Write-Log "유지보수 실패: $($Response.error_message)" "ERROR"
        exit 1
    }
} catch {
    Write-Log "API 호출 실패: $($_.Exception.Message)" "ERROR"
    exit 1
}

Write-Log "============================================"
Write-Log "일별 유지보수 완료"
Write-Log "============================================"

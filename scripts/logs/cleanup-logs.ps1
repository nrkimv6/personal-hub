# scripts/cleanup-logs.ps1
# 로그 파일 자동 정리 스크립트
# 사용법: .\scripts\cleanup-logs.ps1 [-RetentionDays 2] [-DryRun] [-Verbose]

param(
    [int]$RetentionDays = 2,      # 보관 일수 (기본: 2일)
    [switch]$DryRun,              # 테스트 모드 (실제 삭제 안함)
    [switch]$Verbose              # 상세 출력
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# 정리 대상 디렉토리 (logs/ + logs/admin/)
$LogDirs = @(
    (Join-Path $ProjectRoot "logs"),
    (Join-Path $ProjectRoot "logs\admin")
)

# 삭제 대상 패턴
$Patterns = @(
    "api_*.log",
    "worker_*.log",
    "frontend_*.log",
    "stdout_*.log",
    "stderr_*.log",
    "service_runner_*.log",
    "watchdog_*.log",
    "unified_watchdog_*.log",
    "claude_watchdog_*.log",
    "video_download_watchdog_*.log",
    "crawl_watchdog_*.log",
    "command_listener_watchdog_*.log",
    "cloudflared_*.log",
    "cloudflared_err-*.log",
    "cloudflared-*.log",
    "cloudflared_err_*.log",
    "service_MonitorPage*.log",
    "test_results*.log",
    "test_std*.log",
    "llm_worker_*.log",
    "crawl_worker_*.log",
    "dev_runner_command_listener_*.log"
)

$CutoffDate = (Get-Date).AddDays(-$RetentionDays)
$DeletedCount = 0
$DeletedSize = 0
$TargetFiles = @()

foreach ($LogDir in $LogDirs) {
    if (-not (Test-Path $LogDir)) { continue }

    foreach ($Pattern in $Patterns) {
        $Files = Get-ChildItem -Path $LogDir -Filter $Pattern -File -ErrorAction SilentlyContinue |
                 Where-Object { $_.LastWriteTime -lt $CutoffDate }

        foreach ($File in $Files) {
            $TargetFiles += $File
            if ($DryRun) {
                Write-Host "[DRY-RUN] Would delete: $($File.FullName) ($('{0:N2}' -f ($File.Length/1MB)) MB) - Last modified: $($File.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
            } else {
                Remove-Item $File.FullName -Force
                $DeletedCount++
                $DeletedSize += $File.Length
                if ($Verbose) {
                    Write-Host "Deleted: $($File.FullName)"
                }
            }
        }
    }

    # === Catch-all: 패턴에 잡히지 않은 .log 파일도 오래되면 삭제 ===
    $catchallRetention = 7  # catch-all은 7일로 넉넉하게
    $catchallCutoff = (Get-Date).AddDays(-$catchallRetention)
    $protected = @("cleanup.log")

    $catchallFiles = Get-ChildItem -Path $LogDir -Filter "*.log" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt $catchallCutoff -and $_.Name -notin $protected }

    foreach ($File in $catchallFiles) {
        $TargetFiles += $File
        if ($DryRun) {
            Write-Host "[DRY-RUN][CATCH-ALL] Would delete: $($File.FullName) ($('{0:N2}' -f ($File.Length/1MB)) MB)"
        } else {
            Remove-Item $File.FullName -Force
            $DeletedCount++
            $DeletedSize += $File.Length
            if ($Verbose) {
                Write-Host "Deleted (catch-all): $($File.FullName)"
            }
        }
    }
}

# 결과 요약
if ($DryRun) {
    $totalSize = ($TargetFiles | Measure-Object -Property Length -Sum).Sum
    if (-not $totalSize) { $totalSize = 0 }
    $Summary = "Log cleanup DRY-RUN: $($TargetFiles.Count) files would be deleted ($('{0:N2}' -f ($totalSize/1MB)) MB)"
} else {
    $Summary = "Log cleanup complete: $DeletedCount files deleted ($('{0:N2}' -f ($DeletedSize/1MB)) MB)"
}
Write-Host $Summary

# 결과 로깅 (DryRun이 아닐 때만)
if (-not $DryRun) {
    $CleanupLog = Join-Path (Join-Path $ProjectRoot "logs") "cleanup.log"
    $LogEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $Summary (RetentionDays: $RetentionDays, CatchAll: 7d)"
    Add-Content -Path $CleanupLog -Value $LogEntry -Encoding UTF8
}

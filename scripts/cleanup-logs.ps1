# scripts/cleanup-logs.ps1
# 로그 파일 자동 정리 스크립트
# 사용법: .\scripts\cleanup-logs.ps1 [-RetentionDays 3] [-DryRun] [-Verbose]

param(
    [int]$RetentionDays = 3,      # 보관 일수 (기본: 3일)
    [switch]$DryRun,              # 테스트 모드 (실제 삭제 안함)
    [switch]$Verbose              # 상세 출력
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir = Join-Path $ProjectRoot "logs"

# 로그 디렉토리 존재 확인
if (-not (Test-Path $LogDir)) {
    Write-Host "Log directory not found: $LogDir"
    exit 1
}

# 삭제 대상 패턴
$Patterns = @(
    "api_*.log",
    "worker_*.log",
    "frontend_*.log",
    "stdout_*.log"
)

$CutoffDate = (Get-Date).AddDays(-$RetentionDays)
$DeletedCount = 0
$DeletedSize = 0
$TargetFiles = @()

foreach ($Pattern in $Patterns) {
    $Files = Get-ChildItem -Path $LogDir -Filter $Pattern -File -ErrorAction SilentlyContinue |
             Where-Object { $_.LastWriteTime -lt $CutoffDate }

    foreach ($File in $Files) {
        $TargetFiles += $File
        if ($DryRun) {
            Write-Host "[DRY-RUN] Would delete: $($File.Name) ($('{0:N2}' -f ($File.Length/1MB)) MB) - Last modified: $($File.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))"
        } else {
            Remove-Item $File.FullName -Force
            $DeletedCount++
            $DeletedSize += $File.Length
            if ($Verbose) {
                Write-Host "Deleted: $($File.Name)"
            }
        }
    }
}

# 결과 요약
if ($DryRun) {
    $Summary = "Log cleanup DRY-RUN: $($TargetFiles.Count) files would be deleted ($('{0:N2}' -f (($TargetFiles | Measure-Object -Property Length -Sum).Sum/1MB)) MB)"
} else {
    $Summary = "Log cleanup complete: $DeletedCount files deleted ($('{0:N2}' -f ($DeletedSize/1MB)) MB)"
}
Write-Host $Summary

# 결과 로깅 (DryRun이 아닐 때만)
if (-not $DryRun) {
    $CleanupLog = Join-Path $LogDir "cleanup.log"
    $LogEntry = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $Summary (RetentionDays: $RetentionDays)"
    Add-Content -Path $CleanupLog -Value $LogEntry -Encoding UTF8
}

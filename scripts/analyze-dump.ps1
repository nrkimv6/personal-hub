# MEMORY.DMP 크래시 덤프 자동 분석 스크립트
# 관리자 권한으로 실행 필요
# 사용법: powershell -ExecutionPolicy Bypass -File analyze-dump.ps1

$ErrorActionPreference = "Stop"

# 경로 설정
$kd = "$env:LOCALAPPDATA\Microsoft\WindowsApps\kdX64.exe"
$dump = "C:\Windows\MEMORY.DMP"
$sympath = "srv*C:\symbols*https://msdl.microsoft.com/download/symbols"
$outDir = "D:\work\project\tools\monitor-page\docs\reports"
$outFile = "$outDir\dump-analysis-$(Get-Date -Format 'yyyyMMdd-HHmmss').txt"

# 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Error "관리자 권한이 필요합니다. 관리자로 PowerShell을 실행하세요."
    exit 1
}

# kdX64.exe 존재 확인
if (-not (Test-Path $kd)) {
    Write-Error "WinDbg(kdX64.exe)를 찾을 수 없습니다: $kd"
    exit 1
}

if (-not (Test-Path $dump)) {
    Write-Error "덤프 파일을 찾을 수 없습니다: $dump"
    exit 1
}

Write-Host "=== 크래시 덤프 분석 시작 ===" -ForegroundColor Cyan
Write-Host "덤프: $dump"
Write-Host "출력: $outFile"
Write-Host "심볼 다운로드 중 (첫 실행 시 수 분 소요)..."

# 분석 명령 파일 생성
$cmdFile = [System.IO.Path]::GetTempFileName() + ".txt"
@"
!analyze -v
lm t n
!thread
q
"@ | Set-Content $cmdFile -Encoding ASCII

# kd 실행
& $kd -z $dump -y $sympath -c "`$`$<$cmdFile" 2>&1 | Tee-Object -FilePath $outFile

Remove-Item $cmdFile -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== 분석 완료 ===" -ForegroundColor Green
Write-Host "결과 파일: $outFile"

# 핵심 정보 추출
Write-Host ""
Write-Host "=== 핵심 결과 요약 ===" -ForegroundColor Yellow
$content = Get-Content $outFile -ErrorAction SilentlyContinue
if ($content) {
    # MODULE_NAME, IMAGE_NAME, FAULTING_SOURCE 추출
    $content | Select-String -Pattern "MODULE_NAME:|IMAGE_NAME:|FAULTING_SOURCE_MODULE_NAME:|STACK_TEXT:|FAILURE_BUCKET_ID:" | Select-Object -First 20
}

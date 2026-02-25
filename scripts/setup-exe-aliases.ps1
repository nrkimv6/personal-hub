# Monitor Page - exe alias 설정 스크립트
#
# python.exe를 역할별 이름으로 복사하여 Task Manager에서 프로세스 구별 가능하게 합니다.
# Python/가상환경 업데이트 후 재실행이 필요합니다.
#
# 사용법:
#   .\setup-exe-aliases.ps1             # 없는 alias만 생성
#   .\setup-exe-aliases.ps1 -Force      # 기존 alias도 강제 덮어쓰기
#   .\setup-exe-aliases.ps1 -Status     # 현재 alias 상태 확인
#   .\setup-exe-aliases.ps1 -Remove     # 모든 alias 삭제
#
# 주의사항:
#   - Python/venv 업데이트(pip upgrade, venv 재생성) 후 재실행 필요
#   - Microsoft Store 설치 Python은 서명 문제로 불가 (python.org 설치본만 지원)
#   - 안티바이러스가 이름 변경된 exe를 의심할 수 있음 (드문 경우)

param(
    [switch]$Force,   # 기존 alias 강제 덮어쓰기
    [switch]$Status,  # 상태 확인만
    [switch]$Remove   # 모든 alias 삭제
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvScripts = Join-Path $ProjectRoot ".venv\Scripts"
$PythonExe = Join-Path $VenvScripts "python.exe"
$PowershellExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"

# 역할별 exe alias 정의 (Python)
# key: exe 이름 (확장자 제외), value: 역할 설명
$Aliases = [ordered]@{
    "monitorpage-api"         = "API 서버 (prod/dev)"
    "monitorpage-dev"         = "API 서버 (dev 전용)"
    "monitorpage-worker"      = "통합 브라우저 워커"
    "monitorpage-claude"      = "Claude Worker"
    "monitorpage-cmdlistener" = "Redis Command Listener"
    "monitorpage-classifier"  = "Image Classifier"
    "monitorpage-proxy"       = "Proxy Manager"
}

# 역할별 exe alias 정의 (PowerShell)
$PsAliases = [ordered]@{
    "monitorpage-logs"          = "로그 뷰어 supervisor"
    "monitorpage-startup"       = "브라우저 워커 시작 supervisor"
    "monitorpage-apiwatchdog"   = "API Watchdog supervisor"
    "monitorpage-wdog-worker"   = "Worker Watchdog (unified)"
    "monitorpage-wdog-claude"   = "Claude Worker Watchdog"
    "monitorpage-wdog-cmd"      = "Command Listener Watchdog"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page - EXE Alias Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# venv 존재 확인
if (-not (Test-Path $PythonExe)) {
    Write-Host "[ERROR] python.exe not found at: $PythonExe" -ForegroundColor Red
    Write-Host "        Please create a virtual environment first:" -ForegroundColor Yellow
    Write-Host "        python -m venv .venv" -ForegroundColor Yellow
    exit 1
}

# 상태 확인 모드
if ($Status) {
    Write-Host "Virtual Env: $VenvScripts" -ForegroundColor Gray
    Write-Host ""
    Write-Host "Python Alias Status:" -ForegroundColor Cyan
    foreach ($name in $Aliases.Keys) {
        $dest = Join-Path $VenvScripts "$name.exe"
        $role = $Aliases[$name]
        if (Test-Path $dest) {
            $srcHash = (Get-FileHash $PythonExe -Algorithm MD5).Hash
            $dstHash = (Get-FileHash $dest -Algorithm MD5).Hash
            if ($srcHash -eq $dstHash) {
                Write-Host "  [OK] $name.exe  ($role)" -ForegroundColor Green
            } else {
                Write-Host "  [OUTDATED] $name.exe  ($role) — python.exe가 업데이트됨, 재실행 필요" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  [ ] $name.exe  ($role)" -ForegroundColor Gray
        }
    }
    Write-Host ""
    
    Write-Host "PowerShell Alias Status:" -ForegroundColor Cyan
    foreach ($name in $PsAliases.Keys) {
        $dest = Join-Path $VenvScripts "$name.exe"
        $role = $PsAliases[$name]
        if (Test-Path $dest) {
            $srcHash = (Get-FileHash $PowershellExe -Algorithm MD5).Hash
            $dstHash = (Get-FileHash $dest -Algorithm MD5).Hash
            if ($srcHash -eq $dstHash) {
                Write-Host "  [OK] $name.exe  ($role)" -ForegroundColor Green
            } else {
                Write-Host "  [OUTDATED] $name.exe  ($role) — powershell.exe가 업데이트됨, 재실행 필요" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  [ ] $name.exe  ($role)" -ForegroundColor Gray
        }
    }
    Write-Host ""

    # 현재 실행 중인 alias 프로세스 확인
    Write-Host "Running Processes:" -ForegroundColor Cyan
    $found = $false
    foreach ($name in ($Aliases.Keys + $PsAliases.Keys)) {
        $procs = Get-Process -Name $name -ErrorAction SilentlyContinue
        if ($procs) {
            foreach ($p in $procs) {
                Write-Host "  [+] $name  PID=$($p.Id)  MEM=$([math]::Round($p.WorkingSet64/1MB, 1))MB" -ForegroundColor Green
            }
            $found = $true
        }
    }
    if (-not $found) {
        Write-Host "  (none running)" -ForegroundColor Gray
    }
    Write-Host ""
    exit 0
}

# 삭제 모드
if ($Remove) {
    Write-Host "Removing aliases..." -ForegroundColor Yellow
    foreach ($name in ($Aliases.Keys + $PsAliases.Keys)) {
        $dest = Join-Path $VenvScripts "$name.exe"
        if (Test-Path $dest) {
            Remove-Item $dest -Force
            Write-Host "  [REMOVED] $name.exe" -ForegroundColor Yellow
        } else {
            Write-Host "  [SKIP] $name.exe (not found)" -ForegroundColor Gray
        }
    }
    Write-Host ""
    Write-Host "All aliases removed." -ForegroundColor Green
    Write-Host "Note: Start scripts will fall back to python.exe." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

# 생성/업데이트 모드
Write-Host "Virtual Env: $VenvScripts" -ForegroundColor Gray
Write-Host "Source (Python):      python.exe ($((Get-Item $PythonExe).Length / 1KB -as [int]) KB)" -ForegroundColor Gray
if (Test-Path $PowershellExe) {
    Write-Host "Source (PowerShell):  powershell.exe ($((Get-Item $PowershellExe).Length / 1KB -as [int]) KB)" -ForegroundColor Gray
}
Write-Host ""
Write-Host "Creating aliases..." -ForegroundColor Cyan

$created = 0
$skipped = 0
$updated = 0

foreach ($name in $Aliases.Keys) {
    $dest = Join-Path $VenvScripts "$name.exe"
    $role = $Aliases[$name]

    if (Test-Path $dest) {
        if ($Force) {
            Copy-Item $PythonExe $dest -Force
            Write-Host "  [UPDATED] $name.exe  ($role)" -ForegroundColor Yellow
            $updated++
        } else {
            # MD5 체크로 outdated 여부 판단
            $srcHash = (Get-FileHash $PythonExe -Algorithm MD5).Hash
            $dstHash = (Get-FileHash $dest -Algorithm MD5).Hash
            if ($srcHash -ne $dstHash) {
                Copy-Item $PythonExe $dest -Force
                Write-Host "  [UPDATED] $name.exe  ($role) — python.exe 변경 감지" -ForegroundColor Yellow
                $updated++
            } else {
                Write-Host "  [SKIP]    $name.exe  ($role) — 이미 최신" -ForegroundColor Gray
                $skipped++
            }
        }
    } else {
        Copy-Item $PythonExe $dest
        Write-Host "  [CREATED] $name.exe  ($role)" -ForegroundColor Green
        $created++
    }
}

foreach ($name in $PsAliases.Keys) {
    $dest = Join-Path $VenvScripts "$name.exe"
    $role = $PsAliases[$name]

    if (-not (Test-Path $PowershellExe)) {
        Write-Host "  [ERROR]   powershell.exe not found at $PowershellExe" -ForegroundColor Red
        continue
    }

    if (Test-Path $dest) {
        if ($Force) {
            Copy-Item $PowershellExe $dest -Force
            Write-Host "  [UPDATED] $name.exe  ($role)" -ForegroundColor Yellow
            $updated++
        } else {
            # MD5 체크로 outdated 여부 판단
            $srcHash = (Get-FileHash $PowershellExe -Algorithm MD5).Hash
            $dstHash = (Get-FileHash $dest -Algorithm MD5).Hash
            if ($srcHash -ne $dstHash) {
                Copy-Item $PowershellExe $dest -Force
                Write-Host "  [UPDATED] $name.exe  ($role) — powershell.exe 변경 감지" -ForegroundColor Yellow
                $updated++
            } else {
                Write-Host "  [SKIP]    $name.exe  ($role) — 이미 최신" -ForegroundColor Gray
                $skipped++
            }
        }
    } else {
        Copy-Item $PowershellExe $dest
        Write-Host "  [CREATED] $name.exe  ($role)" -ForegroundColor Green
        $created++
    }
}

Write-Host ""
Write-Host "Done: created=$created, updated=$updated, skipped=$skipped" -ForegroundColor Cyan
Write-Host ""
Write-Host "Usage in start scripts:" -ForegroundColor White
Write-Host "  & `"$VenvScripts\monitorpage-api.exe`" app/main.py --port 8000" -ForegroundColor Gray
Write-Host "  & `"$VenvScripts\monitorpage-worker.exe`" scripts/browser_workers.py" -ForegroundColor Gray
Write-Host "  & `"$VenvScripts\monitorpage-claude.exe`" app/workers/claude_worker.py" -ForegroundColor Gray
Write-Host ""
Write-Host "Run again after venv recreation or Python upgrade." -ForegroundColor Yellow
Write-Host ""

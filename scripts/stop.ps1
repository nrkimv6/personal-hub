# Monitor Page - 프로세스 종료 스크립트
# FastAPI 서버와 모니터링 워커를 종료합니다. (좀비 프로세스 강제 종료 포함)

$ErrorActionPreference = "SilentlyContinue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir

# PID 파일 경로
$PidDir = Join-Path $ProjectRoot ".pids"
$ApiPidFile = Join-Path $PidDir "api.pid"
$WorkerPidFile = Join-Path $PidDir "worker.pid"

Write-Host "`n========================================" -ForegroundColor Red
Write-Host "  Monitor Page 프로세스 종료" -ForegroundColor Red
Write-Host "========================================" -ForegroundColor Red
Write-Host ""

# 프로세스 종료 함수
function Stop-MonitorProcess {
    param(
        [string]$Name,
        [string]$PidFile
    )

    $stopped = $false

    # PID 파일에서 프로세스 종료
    if (Test-Path $PidFile) {
        $pid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($pid) {
            $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
            if ($process) {
                Write-Host "[*] $Name 종료 중 (PID: $pid)..." -ForegroundColor Yellow

                # 정상 종료 시도
                $process | Stop-Process -ErrorAction SilentlyContinue

                # 잠시 대기
                Start-Sleep -Seconds 2

                # 여전히 실행 중이면 강제 종료
                $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if ($process) {
                    Write-Host "[!] $Name 강제 종료 중..." -ForegroundColor Red
                    $process | Stop-Process -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 1
                }

                # 최종 확인
                $process = Get-Process -Id $pid -ErrorAction SilentlyContinue
                if (-not $process) {
                    Write-Host "[+] $Name 종료됨 (PID: $pid)" -ForegroundColor Green
                    $stopped = $true
                } else {
                    Write-Host "[-] $Name 종료 실패 (PID: $pid)" -ForegroundColor Red
                }
            } else {
                Write-Host "[*] $Name 프로세스가 이미 종료됨 (PID: $pid)" -ForegroundColor Gray
                $stopped = $true
            }
        }
        # PID 파일 삭제
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "[*] $Name PID 파일 없음" -ForegroundColor Gray
    }

    return $stopped
}

# 좀비 프로세스 검색 및 종료 함수
function Stop-ZombieProcesses {
    param([string]$Pattern, [string]$Name)

    $zombies = Get-WmiObject Win32_Process | Where-Object {
        $_.CommandLine -like "*$Pattern*" -and $_.Name -eq "python.exe"
    }

    if ($zombies) {
        Write-Host "`n[!] $Name 관련 좀비 프로세스 발견:" -ForegroundColor Yellow
        foreach ($zombie in $zombies) {
            Write-Host "    PID: $($zombie.ProcessId) - $($zombie.CommandLine.Substring(0, [Math]::Min(80, $zombie.CommandLine.Length)))..." -ForegroundColor Gray

            try {
                Stop-Process -Id $zombie.ProcessId -Force -ErrorAction Stop
                Write-Host "    [+] 종료됨" -ForegroundColor Green
            } catch {
                Write-Host "    [-] 종료 실패: $_" -ForegroundColor Red
            }
        }
    }
}

# 1. PID 파일 기반 종료
Write-Host "[1] PID 파일 기반 프로세스 종료" -ForegroundColor Cyan
Write-Host "-" * 40

Stop-MonitorProcess -Name "API 서버" -PidFile $ApiPidFile
Stop-MonitorProcess -Name "워커" -PidFile $WorkerPidFile

# 2. 좀비 프로세스 검색 및 종료
Write-Host "`n[2] 좀비 프로세스 검색 및 종료" -ForegroundColor Cyan
Write-Host "-" * 40

# app.main (API 서버) 관련 좀비 프로세스
Stop-ZombieProcesses -Pattern "app.main" -Name "API 서버"
Stop-ZombieProcesses -Pattern "uvicorn" -Name "Uvicorn"

# app.worker.monitor_worker (워커) 관련 좀비 프로세스
Stop-ZombieProcesses -Pattern "app.worker.monitor_worker" -Name "워커"

# 3. 브라우저 프로세스 종료 (선택적)
Write-Host "`n[3] 관련 브라우저 프로세스 확인" -ForegroundColor Cyan
Write-Host "-" * 40

$browserDataPath = Join-Path $ProjectRoot "browser_data"
$chromeProcesses = Get-WmiObject Win32_Process | Where-Object {
    $_.Name -eq "chrome.exe" -and $_.CommandLine -like "*$browserDataPath*"
}

if ($chromeProcesses) {
    Write-Host "[?] 모니터링용 Chrome 프로세스가 발견되었습니다." -ForegroundColor Yellow
    Write-Host "    프로세스 수: $($chromeProcesses.Count)"

    $response = Read-Host "    종료하시겠습니까? (y/N)"
    if ($response -eq "y" -or $response -eq "Y") {
        foreach ($chrome in $chromeProcesses) {
            try {
                Stop-Process -Id $chrome.ProcessId -Force -ErrorAction Stop
                Write-Host "    [+] Chrome 종료됨 (PID: $($chrome.ProcessId))" -ForegroundColor Green
            } catch {
                Write-Host "    [-] Chrome 종료 실패 (PID: $($chrome.ProcessId))" -ForegroundColor Red
            }
        }
    }
} else {
    Write-Host "[*] 관련 Chrome 프로세스 없음" -ForegroundColor Gray
}

# 4. 브라우저 프로필 잠금 파일 정리
$lockFile = Join-Path $browserDataPath "browser_profile\lockfile"
if (Test-Path $lockFile) {
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
    Write-Host "`n[+] 브라우저 프로필 잠금 파일 삭제됨" -ForegroundColor Green
}

Write-Host "`n========================================" -ForegroundColor Green
Write-Host "  프로세스 종료 완료" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

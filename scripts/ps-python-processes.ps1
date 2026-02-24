# Monitor Page - Python 프로세스 CommandLine 필터링 유틸리티
#
# Task Manager에서 python.exe로만 표시되는 프로세스를 역할별로 구별하여 관리합니다.
# exe alias(setup-exe-aliases.ps1) 없이도 즉시 사용 가능.
#
# 사용법:
#   .\ps-python-processes.ps1                    # 전체 Python 프로세스 목록
#   .\ps-python-processes.ps1 -Kill "browser_workers"   # 패턴 매칭 프로세스 종료
#   .\ps-python-processes.ps1 -Kill "app/main.py --port 8001"
#   .\ps-python-processes.ps1 -Watch             # 5초마다 자동 새로고침
#
# ※ alias exe가 설정된 경우 monitorpage-*.exe 프로세스도 함께 표시됩니다.

param(
    [string]$Kill,        # 이 패턴을 CommandLine에 포함한 프로세스 종료
    [switch]$Watch,       # 5초마다 자동 새로고침
    [int]$Interval = 5    # Watch 모드 갱신 주기 (초)
)

# ============================================================
# 역할 추론 (cmdline 패턴 → 역할명)
# ============================================================
function Get-ProcessRole {
    param([string]$CmdLine)
    if (-not $CmdLine) { return '<no cmdline>' }

    $patterns = [ordered]@{
        'app/main.py.*--port 8000'    = 'API (prod :8000)'
        'app/main.py.*--port 8001'    = 'API (dev  :8001)'
        'app/main.py'                 = 'API (server)'
        '-m app.main'                 = 'API (server)'
        'browser_workers'             = '통합 워커'
        'claude_worker'               = 'Claude Worker'
        'image_classif'               = 'Classifier'
        'proxy'                       = 'Proxy Manager'
        'pytest'                      = 'pytest'
        'pip '                        = 'pip'
    }

    foreach ($pattern in $patterns.Keys) {
        if ($CmdLine -match $pattern) {
            return $patterns[$pattern]
        }
    }

    # 매칭 안 되면 cmdline 축약 표시
    $short = $CmdLine -replace '^.*python[w]?\.exe["\s]*', ''
    if ($short.Length -gt 60) { $short = $short.Substring(0, 60) + '...' }
    return $short.Trim()
}

# ============================================================
# 프로세스 목록 조회
# ============================================================
function Show-PythonProcesses {
    $processNames = @('python', 'pythonw',
        'monitorpage-api', 'monitorpage-dev',
        'monitorpage-worker', 'monitorpage-claude',
        'monitorpage-classifier', 'monitorpage-proxy')

    $rows = @()

    # WMI로 CommandLine 포함 정보 조회
    $wmProcs = Get-CimInstance Win32_Process -Filter "name LIKE 'python%' OR name LIKE 'monitorpage-%'" -ErrorAction SilentlyContinue

    foreach ($p in $wmProcs) {
        $memMB = [math]::Round($p.WorkingSetSize / 1MB, 1)
        $role = Get-ProcessRole -CmdLine $p.CommandLine

        $rows += [PSCustomObject]@{
            PID        = $p.ProcessId
            Name       = $p.Name
            Role       = $role
            'Mem(MB)'  = $memMB
            CmdLine    = if ($p.CommandLine) {
                $c = $p.CommandLine -replace '^.*python[w]?\.exe["\s]*', ''
                if ($c.Length -gt 80) { $c.Substring(0, 80) + '...' } else { $c }
            } else { '<access denied>' }
        }
    }

    if ($rows.Count -eq 0) {
        Write-Host "  (No Python processes found)" -ForegroundColor Gray
        return
    }

    # 메모리 내림차순 정렬
    $rows | Sort-Object 'Mem(MB)' -Descending | Format-Table PID, Name, Role, 'Mem(MB)', CmdLine -AutoSize
}

# ============================================================
# 프로세스 종료
# ============================================================
function Stop-PythonByPattern {
    param([string]$Pattern)

    $procs = Get-CimInstance Win32_Process -Filter "name LIKE 'python%' OR name LIKE 'monitorpage-%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$Pattern*" }

    if (-not $procs) {
        Write-Host "[!] No processes matched: '$Pattern'" -ForegroundColor Yellow
        return
    }

    foreach ($p in $procs) {
        $role = Get-ProcessRole -CmdLine $p.CommandLine
        Write-Host "  Stopping PID $($p.ProcessId) [$role]: $($p.Name)" -ForegroundColor Yellow
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "  -> Stopped" -ForegroundColor Green
    }
}

# ============================================================
# 메인 실행
# ============================================================

# 종료 모드
if ($Kill) {
    Write-Host ""
    Write-Host "Killing processes matching: '$Kill'" -ForegroundColor Red
    Write-Host ""
    Stop-PythonByPattern -Pattern $Kill
    Write-Host ""
    exit 0
}

# Watch 모드
if ($Watch) {
    Write-Host "Watching Python processes (Ctrl+C to stop, refresh every ${Interval}s)..." -ForegroundColor Cyan
    while ($true) {
        Clear-Host
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  Monitor Page - Python Processes" -ForegroundColor Cyan
        Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  (refresh: ${Interval}s)" -ForegroundColor Gray
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host ""
        Show-PythonProcesses
        Start-Sleep -Seconds $Interval
    }
    exit 0
}

# 일회성 목록 표시
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Monitor Page - Python Processes" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Show-PythonProcesses
Write-Host ""
Write-Host "Quick commands:" -ForegroundColor Gray
Write-Host "  .\ps-python-processes.ps1 -Kill 'browser_workers'     # 워커 종료" -ForegroundColor Gray
Write-Host "  .\ps-python-processes.ps1 -Kill 'app/main.py'         # API 종료" -ForegroundColor Gray
Write-Host "  .\ps-python-processes.ps1 -Watch                      # 실시간 모니터링" -ForegroundColor Gray
Write-Host ""

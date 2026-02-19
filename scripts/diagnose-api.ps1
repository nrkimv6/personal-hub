# API Down Diagnostics Script
# Diagnoses why the API server is down by running step-by-step tests
#
# Diagnosis flow:
#   1. API health check (HTTP)
#   2. Port LISTEN check (netstat)
#   3. Python basic test (timeout 5s)
#   4. SQLAlchemy import test (timeout 10s)
#   5. DB connection test (timeout 5s)
#   6. app.main import test (timeout 15s)
#   7. death_log.json reference (if exists)
#
# Usage:
#   .\scripts\diagnose-api.ps1 -Dev                    # Diagnose dev API (port 8001)
#   .\scripts\diagnose-api.ps1                         # Diagnose prod API (port 8000)
#   .\scripts\diagnose-api.ps1 -Dev -OutputJson path   # Output JSON to file
#   .\scripts\diagnose-api.ps1 -Dev -Watch             # Watch mode (30s interval)

param(
    [switch]$Dev,
    [string]$OutputJson,
    [switch]$Watch,
    [int]$WatchInterval = 30,
    [switch]$Verbose
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# Configuration
$port = if ($Dev) { 8001 } else { 8000 }
$mode = if ($Dev) { "Development" } else { "Production" }
$healthEndpoint = "http://localhost:$port/api/v1/system/status"

# Default OutputJson path
if (-not $OutputJson) {
    $OutputJson = Join-Path $ProjectRoot "frontend\static\diagnostics.json"
}

# Severity mapping
$SeverityMap = @{
    "api_healthy"       = "ok"
    "api_starting"      = "warning"
    "python_hang"       = "critical"
    "sqlalchemy_hang"   = "critical"
    "db_locked"         = "error"
    "db_migration_error" = "warning"
    "import_error"      = "error"
    "unknown"           = "critical"
}

$ActionMap = @{
    "api_healthy"       = ""
    "api_starting"      = "API가 시작 중입니다. 잠시 대기하세요."
    "python_hang"       = "시스템 재부팅이 필요합니다."
    "sqlalchemy_hang"   = "zombie python 프로세스 kill 또는 재부팅이 필요합니다."
    "db_locked"         = "DB lock 보유 프로세스를 kill하세요."
    "db_migration_error" = "마이그레이션 SQL을 실행하세요."
    "import_error"      = "코드 수정이 필요합니다."
    "unknown"           = "로그를 확인하세요."
}

$MessageMap = @{
    "api_healthy"       = "API가 정상 작동 중입니다."
    "api_starting"      = "API 서버가 시작 중입니다 (포트 미오픈)."
    "python_hang"       = "Python 기본 실행이 응답하지 않습니다."
    "sqlalchemy_hang"   = "SQLAlchemy import가 10초 이상 응답하지 않습니다."
    "db_locked"         = "SQLite DB가 잠겨 있습니다."
    "db_migration_error" = "DB 마이그레이션 실패로 서버를 시작할 수 없습니다."
    "import_error"      = "app.main import 중 에러가 발생했습니다."
    "unknown"           = "원인을 분류할 수 없습니다."
}

function Write-DiagLog {
    param(
        [string]$Message,
        [string]$Level = "INFO"
    )

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $color = switch ($Level) {
        "ERROR"   { "Red" }
        "WARN"    { "Yellow" }
        "INFO"    { "Cyan" }
        "OK"      { "Green" }
        "DEBUG"   { "DarkGray" }
        "STEP"    { "White" }
        default   { "White" }
    }

    if ($Level -eq "DEBUG" -and -not $Verbose) { return }
    Write-Host "[$timestamp] [$Level] $Message" -ForegroundColor $color
}

function Get-ZombieProcesses {
    $zombies = @()
    $pythonProcesses = Get-Process -Name "python*" -ErrorAction SilentlyContinue

    foreach ($proc in $pythonProcesses) {
        try { $startTime = $proc.StartTime } catch { continue }
        if (-not $startTime) { continue }
        $runtime = (Get-Date) - $startTime
        $zombies += @{
            pid        = $proc.Id
            started    = $startTime.ToString("yyyy-MM-ddTHH:mm:ss")
            memory_mb  = [math]::Round($proc.WorkingSet64 / 1MB, 1)
            runtime_hours = [math]::Round($runtime.TotalHours, 1)
            is_zombie  = ($runtime.TotalHours -ge 24)
        }
    }

    return $zombies
}

function Get-DeathLogInfo {
    $deathLogPath = Join-Path $ProjectRoot "logs\death_log.json"

    if (-not (Test-Path $deathLogPath)) {
        return $null
    }

    try {
        $content = Get-Content $deathLogPath -Raw -ErrorAction Stop | ConvertFrom-Json
        if (-not $content -or $content.Count -eq 0) { return $null }

        # Get last death event
        $lastDeath = if ($content -is [array]) { $content[-1] } else { $content }

        # Count crash loops (deaths in last 5 minutes)
        $fiveMinAgo = (Get-Date).AddMinutes(-5)
        $recentDeaths = 0
        if ($content -is [array]) {
            foreach ($entry in $content) {
                $ts = [datetime]::Parse($entry.timestamp)
                if ($ts -gt $fiveMinAgo) { $recentDeaths++ }
            }
        }

        return @{
            timestamp       = $lastDeath.timestamp
            cause           = $lastDeath.cause
            exit_code       = $lastDeath.exit_code
            crash_loop_count = $recentDeaths
        }
    } catch {
        Write-DiagLog "death_log.json 읽기 실패: $_" "DEBUG"
        return $null
    }
}

function Test-WithTimeout {
    param(
        [string]$Label,
        [string]$PythonCode,
        [int]$TimeoutSeconds
    )

    Write-DiagLog "  $Label (timeout: ${TimeoutSeconds}s)..." "STEP"

    $tempFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()

    try {
        $process = Start-Process -FilePath $PythonExe `
            -ArgumentList "-c", "`"$PythonCode`"" `
            -NoNewWindow -PassThru `
            -RedirectStandardOutput $tempFile `
            -RedirectStandardError $errFile

        $completed = $process.WaitForExit($TimeoutSeconds * 1000)

        if (-not $completed) {
            $process.Kill()
            $process.WaitForExit(3000)
            return @{ success = $false; timeout = $true; output = ""; error = "Timeout after ${TimeoutSeconds}s" }
        }

        $stdout = Get-Content $tempFile -Raw -ErrorAction SilentlyContinue
        $stderr = Get-Content $errFile -Raw -ErrorAction SilentlyContinue
        $exitCode = $process.ExitCode

        if ($exitCode -eq 0) {
            return @{ success = $true; timeout = $false; output = $stdout; error = "" }
        } else {
            return @{ success = $false; timeout = $false; output = $stdout; error = $stderr }
        }
    } catch {
        return @{ success = $false; timeout = $false; output = ""; error = $_.Exception.Message }
    } finally {
        Remove-Item $tempFile -ErrorAction SilentlyContinue
        Remove-Item $errFile -ErrorAction SilentlyContinue
    }
}

function Invoke-Diagnosis {
    $result = @{
        timestamp      = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
        status         = "unknown"
        severity       = "critical"
        message        = ""
        action         = ""
        details        = @{
            api_port        = $port
            port_listening  = $null
            python_ok       = $null
            sqlalchemy_ok   = $null
            db_ok           = $null
            import_ok       = $null
            import_error_message = $null
            zombie_processes = @()
            last_death      = $null
        }
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  API 진단 시작 ($mode, port $port)" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    # Step 1: API Health Check
    Write-DiagLog "Step 1/7: API 헬스체크..." "STEP"
    try {
        $response = Invoke-WebRequest $healthEndpoint -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-DiagLog "  API 정상 (200 OK)" "OK"
            $result.status = "api_healthy"
            $result.severity = "ok"
            $result.message = $MessageMap["api_healthy"]
            $result.action = $ActionMap["api_healthy"]

            # Healthy → delete JSON if exists
            if (Test-Path $OutputJson) {
                Remove-Item $OutputJson -ErrorAction SilentlyContinue
                Write-DiagLog "  diagnostics.json 삭제 (정상)" "DEBUG"
            }

            Write-FinalResult $result
            return $result
        }
    } catch {
        Write-DiagLog "  API 응답 없음" "WARN"
    }

    # Step 2: Port LISTEN check
    Write-DiagLog "Step 2/7: 포트 LISTEN 확인..." "STEP"
    $conn = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Listen' }
    if ($conn) {
        $result.details.port_listening = $true
        $ownerPid = $conn.OwningProcess
        Write-DiagLog "  포트 $port LISTEN 중 (PID: $ownerPid) — 응답은 느린 상태, 추가 진단 진행" "INFO"
    } else {
        $result.details.port_listening = $false
        Write-DiagLog "  포트 $port 미사용" "INFO"
    }

    # Step 3: Python basic test
    Write-DiagLog "Step 3/7: Python 기본 테스트..." "STEP"
    $pythonTest = Test-WithTimeout "python -c 'print(ok)'" "print('ok')" 5
    if ($pythonTest.success) {
        $result.details.python_ok = $true
        Write-DiagLog "  Python OK" "OK"
    } elseif ($pythonTest.timeout) {
        $result.details.python_ok = $false
        Write-DiagLog "  Python HANG (5s timeout)" "ERROR"
        $result.status = "python_hang"
        $result.severity = $SeverityMap["python_hang"]
        $result.message = $MessageMap["python_hang"]
        $result.action = $ActionMap["python_hang"]
        $result.details.zombie_processes = @(Get-ZombieProcesses)
        $result.details.last_death = Get-DeathLogInfo
        Write-OutputJson $result
        Write-FinalResult $result
        return $result
    } else {
        $result.details.python_ok = $false
        Write-DiagLog "  Python 에러: $($pythonTest.error)" "ERROR"
        $result.status = "python_hang"
        $result.severity = $SeverityMap["python_hang"]
        $result.message = "Python 실행 에러: $($pythonTest.error)"
        $result.action = $ActionMap["python_hang"]
        $result.details.zombie_processes = @(Get-ZombieProcesses)
        $result.details.last_death = Get-DeathLogInfo
        Write-OutputJson $result
        Write-FinalResult $result
        return $result
    }

    # Step 4: SQLAlchemy import test
    Write-DiagLog "Step 4/7: SQLAlchemy import 테스트..." "STEP"
    $sqlaTest = Test-WithTimeout "import sqlalchemy" "import sqlalchemy; print('ok')" 10
    if ($sqlaTest.success) {
        $result.details.sqlalchemy_ok = $true
        Write-DiagLog "  SQLAlchemy OK" "OK"
    } elseif ($sqlaTest.timeout) {
        $result.details.sqlalchemy_ok = $false
        Write-DiagLog "  SQLAlchemy HANG (10s timeout)" "ERROR"
        $result.status = "sqlalchemy_hang"
        $result.severity = $SeverityMap["sqlalchemy_hang"]
        $result.message = $MessageMap["sqlalchemy_hang"]
        $result.action = $ActionMap["sqlalchemy_hang"]
        $result.details.zombie_processes = @(Get-ZombieProcesses)
        $result.details.last_death = Get-DeathLogInfo
        Write-OutputJson $result
        Write-FinalResult $result
        return $result
    } else {
        $result.details.sqlalchemy_ok = $false
        Write-DiagLog "  SQLAlchemy 에러: $($sqlaTest.error)" "WARN"
    }

    # Step 5: DB connection test
    Write-DiagLog "Step 5/7: DB 연결 테스트..." "STEP"
    $dbPath = Join-Path $ProjectRoot "data\monitor.db"
    $dbPathFwd = $dbPath -replace '\\', '/'
    $dbTestCode = @'
import sqlite3; conn = sqlite3.connect('DB_PATH', timeout=3); conn.execute('SELECT 1'); conn.close(); print('ok')
'@ -replace 'DB_PATH', $dbPathFwd
    $dbTest = Test-WithTimeout "sqlite3 connect" $dbTestCode 5
    if ($dbTest.success) {
        $result.details.db_ok = $true
        Write-DiagLog "  DB 연결 OK" "OK"
    } elseif ($dbTest.timeout) {
        $result.details.db_ok = $false
        Write-DiagLog "  DB HANG (locked)" "ERROR"
        $result.status = "db_locked"
        $result.severity = $SeverityMap["db_locked"]
        $result.message = $MessageMap["db_locked"]
        $result.action = $ActionMap["db_locked"]
        $result.details.zombie_processes = @(Get-ZombieProcesses)
        $result.details.last_death = Get-DeathLogInfo
        Write-OutputJson $result
        Write-FinalResult $result
        return $result
    } else {
        $result.details.db_ok = $false
        Write-DiagLog "  DB 에러: $($dbTest.error)" "WARN"
    }

    # Step 6: app.main import test
    Write-DiagLog "Step 6/7: app.main import 테스트..." "STEP"
    $projectRootFwd = $ProjectRoot -replace '\\', '/'
    $importCode = @'
import sys; sys.path.insert(0, 'PROJECT_ROOT'); from app.main import app; print('ok')
'@ -replace 'PROJECT_ROOT', $projectRootFwd
    $importTest = Test-WithTimeout "from app.main import app" $importCode 15
    if ($importTest.success) {
        $result.details.import_ok = $true
        Write-DiagLog "  app.main import OK" "OK"
        # Import succeeds but server not running → api_starting
        $result.status = "api_starting"
        $result.severity = $SeverityMap["api_starting"]
        $result.message = $MessageMap["api_starting"]
        $result.action = $ActionMap["api_starting"]
    } elseif ($importTest.timeout) {
        $result.details.import_ok = $false
        Write-DiagLog "  app.main import HANG (15s timeout)" "ERROR"
        $result.status = "import_error"
        $result.severity = $SeverityMap["import_error"]
        $result.message = "app.main import가 15초 이상 응답하지 않습니다."
        $result.action = $ActionMap["import_error"]
    } else {
        $result.details.import_ok = $false
        $errMsg = $importTest.error
        $result.details.import_error_message = $errMsg
        Write-DiagLog "  app.main import 에러" "ERROR"

        # Check for migration keywords
        if ($errMsg -match "migration|migrate|alembic|ALTER|CREATE TABLE") {
            $result.status = "db_migration_error"
            $result.severity = $SeverityMap["db_migration_error"]
            $result.message = $MessageMap["db_migration_error"]
            $result.action = $ActionMap["db_migration_error"]
        } else {
            $result.status = "import_error"
            $result.severity = $SeverityMap["import_error"]
            $result.message = "$($MessageMap['import_error']): $errMsg"
            $result.action = $ActionMap["import_error"]
        }
    }

    # Step 7: death_log.json reference
    Write-DiagLog "Step 7/7: death_log.json 참조..." "STEP"
    $deathInfo = Get-DeathLogInfo
    if ($deathInfo) {
        $result.details.last_death = $deathInfo
        Write-DiagLog "  마지막 사망: $($deathInfo.cause) ($($deathInfo.timestamp)), 크래시 루프: $($deathInfo.crash_loop_count)" "INFO"
    } else {
        Write-DiagLog "  death_log.json 없음" "DEBUG"
    }

    # Collect zombie processes
    $result.details.zombie_processes = @(Get-ZombieProcesses)

    Write-OutputJson $result
    Write-FinalResult $result
    return $result
}

function Write-OutputJson {
    param([hashtable]$Result)

    # Ensure directory exists
    $dir = Split-Path -Parent $OutputJson
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    # Convert to JSON-serializable structure
    $jsonObj = @{
        timestamp = $Result.timestamp
        status    = $Result.status
        severity  = $Result.severity
        message   = $Result.message
        action    = $Result.action
        details   = @{
            api_port             = $Result.details.api_port
            port_listening       = $Result.details.port_listening
            python_ok            = $Result.details.python_ok
            sqlalchemy_ok        = $Result.details.sqlalchemy_ok
            db_ok                = $Result.details.db_ok
            import_ok            = $Result.details.import_ok
            import_error_message = $Result.details.import_error_message
            zombie_processes     = $Result.details.zombie_processes
            last_death           = $Result.details.last_death
        }
    }

    $jsonObj | ConvertTo-Json -Depth 5 | Out-File -FilePath $OutputJson -Encoding utf8 -Force
    Write-DiagLog "JSON 출력: $OutputJson" "INFO"
}

function Write-FinalResult {
    param([hashtable]$Result)

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  진단 결과" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan

    $statusColor = switch ($Result.severity) {
        "ok"       { "Green" }
        "warning"  { "Yellow" }
        "error"    { "Red" }
        "critical" { "DarkRed" }
        default    { "White" }
    }

    $severityIcon = switch ($Result.severity) {
        "ok"       { [char]0x2705 }  # green check
        "warning"  { [char]0x26A0 }  # warning
        "error"    { [char]::ConvertFromUtf32(0x1F7E0) } # orange
        "critical" { [char]::ConvertFromUtf32(0x1F534) } # red circle
        default    { "?" }
    }

    Write-Host "  상태: $severityIcon $($Result.status)" -ForegroundColor $statusColor
    Write-Host "  메시지: $($Result.message)" -ForegroundColor $statusColor
    if ($Result.action) {
        Write-Host "  조치: $($Result.action)" -ForegroundColor Yellow
    }

    # Show zombie processes
    if ($Result.details.zombie_processes.Count -gt 0) {
        Write-Host ""
        Write-Host "  Python 프로세스 목록:" -ForegroundColor Gray
        foreach ($z in $Result.details.zombie_processes) {
            $zombieTag = if ($z.is_zombie) { " [ZOMBIE 24h+]" } else { "" }
            Write-Host "    PID $($z.pid) | 시작: $($z.started) | 메모리: $($z.memory_mb)MB | 실행: $($z.runtime_hours)h$zombieTag" -ForegroundColor Gray
        }
    }

    # Show last death
    if ($Result.details.last_death) {
        $d = $Result.details.last_death
        Write-Host ""
        Write-Host "  마지막 사망 기록:" -ForegroundColor Gray
        Write-Host "    시간: $($d.timestamp) | 원인: $($d.cause) | 종료코드: $($d.exit_code) | 크래시루프: $($d.crash_loop_count)회" -ForegroundColor Gray
    }

    Write-Host ""
}

# Main execution
if ($Watch) {
    Write-Host "Watch 모드 시작 (${WatchInterval}초 간격)" -ForegroundColor Cyan
    while ($true) {
        $diagResult = Invoke-Diagnosis

        # If healthy, delete JSON file (auto-hide banner)
        if ($diagResult.status -eq "api_healthy" -and (Test-Path $OutputJson)) {
            Remove-Item $OutputJson -ErrorAction SilentlyContinue
            Write-DiagLog "diagnostics.json 삭제 (API 정상)" "DEBUG"
        }

        Start-Sleep -Seconds $WatchInterval
    }
} else {
    Invoke-Diagnosis | Out-Null
}

# watchdog-utils.ps1
# watchdog 스크립트 공통 유틸리티 함수 모음
#
# 사용 방법 (각 watchdog 스크립트 최상단에서 dot-source):
#   . (Join-Path $ScriptDir "watchdog-utils.ps1")
#
# 전제 조건:
#   - $script:watchdogLogFile 이 호출 스크립트에서 설정되어 있어야 함
#     (Write-Log 함수가 이 변수를 참조)

# ─────────────────────────────────────────────────
# Write-Log: 콘솔 + 파일 동시 출력
# $script:watchdogLogFile 는 dot-source 호출자 스크립트의 스크립트 변수를 사용
# ─────────────────────────────────────────────────
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    Write-Host $logMessage -ForegroundColor $(
        switch ($Level) {
            "ERROR" { "Red" }
            "WARN"  { "Yellow" }
            "INFO"  { "Cyan" }
            default { "White" }
        }
    )
    Add-Content -Path $script:watchdogLogFile -Value $logMessage -Encoding UTF8
}

# ─────────────────────────────────────────────────
# Get-DuplicateProcesses
#   PID 파일의 PID를 "정본"으로 간주하고, 동일 cmdline 패턴의 나머지 프로세스를 반환
#
# 파라미터:
#   -CmdlinePattern  : CommandLine에서 검색할 정규식 패턴
#   -PidFile         : 정본 PID가 기록된 파일 경로
# ─────────────────────────────────────────────────
function Get-DuplicateProcesses {
    param(
        [string]$CmdlinePattern,
        [string]$PidFile
    )

    $canonicalPid = $null
    if (Test-Path $PidFile) {
        $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $canonicalPid = [int]$savedPid
        }
    }

    $allMatching = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $CmdlinePattern }

    if (-not $allMatching) {
        return @()
    }

    $duplicates = $allMatching | Where-Object {
        $_.ProcessId -ne $canonicalPid
    }

    return @($duplicates)
}

# ─────────────────────────────────────────────────
# Remove-DuplicateProcesses
#   중복 프로세스를 감지하고 강제 종료
#
# 파라미터:
#   -Label           : 로그 메시지에 사용할 프로세스 이름 (예: "listener", "worker", "claude worker")
#   -CmdlinePattern  : CommandLine에서 검색할 정규식 패턴
#   -PidFile         : 정본 PID가 기록된 파일 경로
# ─────────────────────────────────────────────────
function Remove-DuplicateProcesses {
    param(
        [string]$Label,
        [string]$CmdlinePattern,
        [string]$PidFile
    )

    $duplicates = Get-DuplicateProcesses -CmdlinePattern $CmdlinePattern -PidFile $PidFile
    if (-not $duplicates -or $duplicates.Count -eq 0) {
        return
    }

    # 중복 종료 전 PID 파일의 정본 프로세스가 실제로 살아있는지 재확인
    $canonicalPid = $null
    if (Test-Path $PidFile) {
        $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($savedPid) { $canonicalPid = [int]$savedPid }
    }
    if ($canonicalPid -and -not (Get-Process -Id $canonicalPid -ErrorAction SilentlyContinue)) {
        Write-Log "정본 PID $canonicalPid 가 이미 죽어 있음 — 중복 정리 건너뜀" "WARN"
        return
    }

    $pids = $duplicates | ForEach-Object { $_.ProcessId }
    $pidList = $pids -join ", "
    Write-Log "중복 $Label $($duplicates.Count)개 감지, 정리함 (PIDs: $pidList)" "WARN"

    foreach ($dup in $duplicates) {
        try {
            Stop-Process -Id $dup.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Log "중복 프로세스 종료: PID $($dup.ProcessId)" "WARN"
        }
        catch {
            Write-Log "중복 프로세스 종료 실패: PID $($dup.ProcessId) — $_" "ERROR"
        }
    }
}

# ─────────────────────────────────────────────────
# Stop-ExistingProcessesByCmdline
#   재시작 직전에 cmdline 패턴으로 기존 프로세스를 모두 종료
#   watchdog 재시작 경로에서 stop()을 거치지 않아도 중복이 생기지 않도록 방어
#
# 파라미터:
#   -Label           : 로그 메시지에 사용할 프로세스 이름
#   -CmdlinePattern  : CommandLine에서 검색할 정규식 패턴
# ─────────────────────────────────────────────────
function Stop-ExistingProcessesByCmdline {
    param(
        [string]$Label,
        [string]$CmdlinePattern
    )

    $existingProcs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $CmdlinePattern }
    if ($existingProcs) {
        $pidList = ($existingProcs | ForEach-Object { $_.ProcessId }) -join ", "
        Write-Log "재시작 전 기존 $Label 프로세스 정리 (PIDs: $pidList)" "WARN"
        foreach ($ep in $existingProcs) {
            try {
                Stop-Process -Id $ep.ProcessId -Force -ErrorAction SilentlyContinue
                Write-Log "기존 프로세스 종료: PID $($ep.ProcessId)" "WARN"
            }
            catch {
                Write-Log "기존 프로세스 종료 실패: PID $($ep.ProcessId) — $_" "ERROR"
            }
        }
        # 프로세스가 완전히 종료될 때까지 최대 5초 대기
        $deadline = (Get-Date).AddSeconds(5)
        while ((Get-Date) -lt $deadline) {
            $still = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -match $CmdlinePattern }
            if (-not $still) { break }
            Start-Sleep -Milliseconds 300
        }
        $remaining = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -match $CmdlinePattern }
        if ($remaining) {
            $pidList2 = ($remaining | ForEach-Object { $_.ProcessId }) -join ", "
            Write-Log "경고: 기존 $Label 프로세스가 아직 살아있음 (PIDs: $pidList2)" "WARN"
        }
    }
}

# ─────────────────────────────────────────────────
# Confirm-ProcessPid
#   Start-Process -PassThru 반환 PID가 실제 Python 프로세스 PID인지 검증.
#   Windows에서 -WindowStyle Hidden + -RedirectStandard* 조합 시 conhost.exe
#   중간 프로세스가 생성되어 PassThru PID가 실제 PID와 다를 수 있음.
#   -NoNewWindow 사용 시에는 이 문제가 없지만, 안전망으로 유지.
#
# 파라미터:
#   -ProcessId        : Start-Process -PassThru 로 받은 PID
#   -NamePattern      : 기대하는 프로세스명 정규식 (예: 'monitorpage-|python')
#   -CmdlinePattern   : cmdline 기반 재탐색용 패턴 (예: 'claude_worker\.worker\.worker')
#
# 반환:
#   검증된 실제 PID (int). 불일치 시 cmdline으로 재탐색한 PID 반환.
#   재탐색 실패 시 원래 PID 반환.
# ─────────────────────────────────────────────────
function Confirm-ProcessPid {
    param(
        [int]$ProcessId,
        [string]$NamePattern,
        [string]$CmdlinePattern
    )

    # 잠시 대기 후 확인 (프로세스 초기화 시간)
    Start-Sleep -Milliseconds 300

    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $proc) {
        Write-Log "PID $ProcessId 가 이미 종료됨 — cmdline 패턴으로 재탐색" "WARN"
    } elseif ($proc.Name -match $NamePattern) {
        # PID 정상 — 그대로 반환
        return $ProcessId
    } else {
        Write-Log "PID $ProcessId 프로세스명 '$($proc.Name)' 이 기대 패턴('$NamePattern')과 불일치 — cmdline 재탐색" "WARN"
    }

    # cmdline 패턴으로 실제 Python 프로세스 탐색
    $realProc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $CmdlinePattern } |
        Sort-Object ProcessId -Descending |
        Select-Object -First 1

    if ($realProc) {
        Write-Log "실제 프로세스 발견: PID $($realProc.ProcessId) (이름: $($realProc.Name))" "INFO"
        return $realProc.ProcessId
    }

    Write-Log "cmdline 재탐색 실패 — 원래 PID $ProcessId 유지" "WARN"
    return $ProcessId
}

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

function Get-WatchdogPaths {
    param([string]$ProjectRoot)

    $isAdmin = $env:APP_MODE -eq "admin"
    $logDir = if ($isAdmin) { Join-Path $ProjectRoot "logs\admin" } else { Join-Path $ProjectRoot "logs" }
    $pidDir = Join-Path $ProjectRoot ".pids"
    $pidSuffix = if ($isAdmin) { "_admin" } else { "" }

    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    if (-not (Test-Path $pidDir)) {
        New-Item -ItemType Directory -Path $pidDir -Force | Out-Null
    }

    return @{
        LogDir = $logDir
        PidDir = $pidDir
        PidSuffix = $pidSuffix
        IsAdmin = $isAdmin
    }
}

function Get-WorkerExecutable {
    param(
        [string]$ProjectRoot,
        [string]$AliasName = ""
    )

    if ($AliasName) {
        $aliasExe = Join-Path $ProjectRoot ".venv\Scripts\$AliasName"
        if (Test-Path $aliasExe) {
            return $aliasExe
        }
    }

    foreach ($candidate in @(".venv\Scripts\python.exe", "venv\Scripts\python.exe")) {
        $pythonExe = Join-Path $ProjectRoot $candidate
        if (Test-Path $pythonExe) {
            return $pythonExe
        }
    }

    return $null
}

# PID 파일 기반 liveness check helper.
# 주의: 이 함수는 cmdline까지 재검증하지 않는다. PID 재활용 가능성은 호출자가
# stale pid 제거 또는 cmdline 기반 orphan 정리와 조합해 방어해야 한다.
function Test-PidFileAlive {
    param([string]$PidFile)

    if (-not (Test-Path $PidFile)) {
        return $false
    }

    $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
    if (-not $savedPid) {
        return $false
    }

    try {
        $targetPid = [int]$savedPid
    } catch {
        return $false
    }

    $process = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    return ($null -ne $process)
}

function Start-WorkerProcess {
    param(
        [string]$Label,
        [string]$Python,
        [string[]]$ArgList,
        [string]$WorkingDir,
        [string]$StdoutLog = "",
        [string]$StderrLog = "",
        [string]$NamePattern,
        [string]$CmdlinePattern,
        [string]$PidFile,
        [hashtable]$Env = @{},
        [string]$RegisterRole = "",
        [string]$RegisterName = "",
        [int]$ParentPid = 0
    )

    Stop-ExistingProcessesByCmdline -Label $Label -CmdlinePattern $CmdlinePattern

    if (-not (Test-Path $Python)) {
        Write-Log "ERROR: worker executable not found: $Python" "ERROR"
        return $null
    }

    $originalEnv = @{}
    foreach ($key in $Env.Keys) {
        $originalEnv[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        [Environment]::SetEnvironmentVariable($key, [string]$Env[$key], "Process")
    }

    try {
        $startParams = @{
            FilePath = $Python
            ArgumentList = $ArgList
            WorkingDirectory = $WorkingDir
            NoNewWindow = $true
            PassThru = $true
        }
        if ($StdoutLog) {
            $startParams.RedirectStandardOutput = $StdoutLog
        }
        if ($StderrLog) {
            $startParams.RedirectStandardError = $StderrLog
        }

        $workerProcess = Start-Process @startParams
    }
    finally {
        foreach ($key in $Env.Keys) {
            [Environment]::SetEnvironmentVariable($key, $originalEnv[$key], "Process")
        }
    }

    $actualPid = Confirm-ProcessPid -ProcessId $workerProcess.Id -NamePattern $NamePattern -CmdlinePattern $CmdlinePattern
    $actualPid | Out-File $PidFile -Encoding ascii

    if ($RegisterRole) {
        $registerName = if ($RegisterName) { $RegisterName } else { $Label }
        $registerScript = Join-Path $WorkingDir "scripts\services\register_process.py"
        & $Python $registerScript --pid $actualPid --ppid $ParentPid --name $registerName --exe $Python --role $RegisterRole -ErrorAction SilentlyContinue
    }

    return $actualPid
}

function Invoke-WatchdogLoop {
    param(
        [string]$Label,
        [ScriptBlock]$StartTarget,
        [ScriptBlock]$TestRunning,
        [int]$CheckInterval,
        [int]$MaxRestarts,
        [int]$RestartWindow,
        [ScriptBlock]$OnExit = $null
    )

    $restartCount = 0
    $lastRestartTime = Get-Date

    if (-not (& $TestRunning)) {
        Write-Log "$Label not running, starting..." "WARN"
        & $StartTarget | Out-Null
        $restartCount++
        $lastRestartTime = Get-Date
    }

    try {
        while ($true) {
            Start-Sleep -Seconds $CheckInterval

            $timeSinceLastRestart = ((Get-Date) - $lastRestartTime).TotalSeconds
            if ($timeSinceLastRestart -gt $RestartWindow) {
                if ($restartCount -gt 0) {
                    Write-Log "Restart count reset (no crashes in ${RestartWindow}s)"
                    $restartCount = 0
                }
            }

            if (-not (& $TestRunning)) {
                Write-Log "$Label process died!" "ERROR"

                if ($restartCount -ge $MaxRestarts) {
                    Write-Log "Maximum restart limit ($MaxRestarts) reached in ${RestartWindow}s window!" "ERROR"
                    Write-Log "Please check the watchdog logs for the root cause." "ERROR"
                    Write-Log "Watchdog stopping to prevent restart loop." "ERROR"
                    break
                }

                Write-Log "Restarting $Label (attempt $($restartCount + 1)/$MaxRestarts)..." "WARN"
                & $StartTarget | Out-Null
                $restartCount++
                $lastRestartTime = Get-Date
            }
        }
    }
    catch {
        Write-Log "Watchdog error: $_" "ERROR"
    }
    finally {
        Write-Log "Watchdog stopped"
        if ($OnExit) {
            & $OnExit
        }
    }
}

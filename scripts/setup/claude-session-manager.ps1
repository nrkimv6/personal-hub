<#
.SYNOPSIS
    Claude Code 세션 관리 스크립트 — 조회, 고아 정리, 강제 종료

.DESCRIPTION
    멈춘 Claude Code CLI 세션을 진단하고 정리하는 유틸리티.
    - 실행 중인 claude.exe 프로세스 목록 (Desktop/gemini 제외)
    - 각 프로세스의 부모 셸 상태 (살아있음/고아)
    - JSONL 세션 로그에서 작업 내용·브랜치·CWD 추출
    - dev-runner/plan-runner 관련 프로세스 확인

.PARAMETER Action
    list    : 실행 중인 세션 목록 + 최근 JSONL 세션 내용 (기본값)
    kill    : 고아 프로세스만 종료 (부모 셸이 죽은 것)
    killall : 현재 세션 제외 전체 종료 (현재 PID를 -ExcludePID로 지정)

.PARAMETER ExcludePID
    종료 대상에서 제외할 PID (현재 실행 중인 세션)

.EXAMPLE
    .\claude-session-manager.ps1                     # 목록 조회
    .\claude-session-manager.ps1 -Action kill        # 고아만 종료
    .\claude-session-manager.ps1 -Action killall -ExcludePID 12345  # 전부 종료 (12345 제외)
#>

param(
    [ValidateSet("list", "kill", "killall")]
    [string]$Action = "list",
    [int]$ExcludePID = 0
)

# ── 1. 실행 중인 Claude CLI 프로세스 수집 ──
# Desktop 앱(WindowsApps), gemini subagent, 현재 제외 PID 필터링
$claudeProcs = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "claude.exe" -and
        $_.CommandLine -notmatch "type=" -and          # Desktop 렌더러/GPU 등
        $_.CommandLine -notmatch "gemini" -and          # gemini subagent 호출
        $_.CommandLine -notmatch "WindowsApps" -and     # Desktop 앱 본체
        $_.ProcessId -ne $ExcludePID
    }

if (-not $claudeProcs) {
    Write-Host "실행 중인 Claude CLI 세션 없음" -ForegroundColor Green
    exit 0
}

# ── 2. 각 프로세스 분석 ──
$results = @()
foreach ($proc in $claudeProcs) {
    $parentProc = Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.ParentProcessId)" -ErrorAction SilentlyContinue
    $parentAlive = $null -ne $parentProc
    $parentName = if ($parentProc) { $parentProc.Name } else { "(dead)" }

    # 부모의 부모 확인 (WindowsTerminal인지, dev-runner인지 판별)
    $grandparent = ""
    if ($parentProc) {
        $gp = Get-CimInstance Win32_Process -Filter "ProcessId = $($parentProc.ParentProcessId)" -ErrorAction SilentlyContinue
        $grandparent = if ($gp) { $gp.Name } else { "" }
    }

    $results += [PSCustomObject]@{
        PID         = $proc.ProcessId
        Start       = $proc.CreationDate.ToString("MM-dd HH:mm")
        ParentPID   = $proc.ParentProcessId
        ParentName  = $parentName
        ParentAlive = $parentAlive
        Grandparent = $grandparent
        Status      = if (-not $parentAlive) { "ORPHAN" } else { "alive" }
    }
}

# ── 3. 목록 출력 ──
Write-Host "`n=== Claude CLI 세션 ($($results.Count)개) ===" -ForegroundColor Cyan
$results | Format-Table PID, Start, Status, ParentName, ParentPID, Grandparent -AutoSize

# ── 4. dev-runner / plan-runner 관련 프로세스 확인 ──
Write-Host "=== dev-runner / plan-runner 프로세스 ===" -ForegroundColor Cyan
$runners = Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match "browser_workers|dev.runner|plan.runner|command.listener" }
if ($runners) {
    foreach ($r in $runners) {
        $cmdShort = $r.CommandLine.Substring(0, [Math]::Min(120, $r.CommandLine.Length))
        Write-Host "  PID=$($r.ProcessId) $($r.Name) | $cmdShort"
    }
} else {
    Write-Host "  (없음)"
}

# ── 5. 최근 JSONL 세션 내용 (작업 파악용) ──
Write-Host "`n=== 최근 JSONL 세션 로그 ===" -ForegroundColor Cyan
$base = "$env:USERPROFILE\.claude\projects\D--work-project-tools-monitor-page"
if (Test-Path $base) {
    $jsonlFiles = Get-ChildItem "$base\*.jsonl" | Sort-Object LastWriteTime -Descending | Select-Object -First 8
    foreach ($f in $jsonlFiles) {
        $mt = $f.LastWriteTime.ToString("MM-dd HH:mm")
        $sid = $f.BaseName.Substring(0, 8)
        $cwd = ""; $msg = ""; $branch = ""
        $reader = [System.IO.StreamReader]::new($f.FullName)
        $count = 0
        while ((-not $reader.EndOfStream) -and $count -lt 100) {
            $line = $reader.ReadLine(); $count++
            try {
                $d = $line | ConvertFrom-Json -ErrorAction Stop
                if ($d.type -eq "user" -and -not $cwd -and $d.cwd) {
                    $cwd = $d.cwd; $branch = $d.gitBranch
                }
                if ($d.type -eq "user" -and -not $msg) {
                    foreach ($c in $d.message.content) {
                        if ($c -is [string] -and -not $c.StartsWith("<")) {
                            $msg = $c.Substring(0, [Math]::Min(80, $c.Length)) -replace "`n", " "; break
                        }
                        if ($c.type -eq "text" -and $c.text -and -not $c.text.StartsWith("<")) {
                            $msg = $c.text.Substring(0, [Math]::Min(80, $c.text.Length)) -replace "`n", " "; break
                        }
                    }
                }
            } catch {}
            if ($cwd -and $msg) { break }
        }
        $reader.Close()
        $cwdShort = if ($cwd) { Split-Path $cwd -Leaf } else { "?" }
        Write-Host "  $mt | $sid | $branch | $cwdShort | $msg"
    }
}

# ── 6. 액션 실행 ──
if ($Action -eq "kill") {
    $orphans = $results | Where-Object { $_.Status -eq "ORPHAN" }
    if ($orphans) {
        Write-Host "`n고아 프로세스 $($orphans.Count)개 종료 중..." -ForegroundColor Yellow
        foreach ($o in $orphans) {
            Stop-Process -Id $o.PID -Force -ErrorAction SilentlyContinue
            Write-Host "  Killed PID $($o.PID) (started $($o.Start))" -ForegroundColor Red
        }
    } else {
        Write-Host "`n고아 프로세스 없음" -ForegroundColor Green
    }
}
elseif ($Action -eq "killall") {
    Write-Host "`n전체 $($results.Count)개 종료 중..." -ForegroundColor Yellow
    foreach ($r in $results) {
        Stop-Process -Id $r.PID -Force -ErrorAction SilentlyContinue
        Write-Host "  Killed PID $($r.PID) ($($r.Status), started $($r.Start))" -ForegroundColor Red
    }
}

Write-Host ""

# kill-orphan-procs.ps1
# 고아 pytest 프로세스 및 연결된 부모 체인(cmd.exe, sh.exe)을 정리한다.
#
# 사용법:
#   .\kill-orphan-procs.ps1           # 고아 pytest + 체인 kill
#   .\kill-orphan-procs.ps1 -DryRun   # 대상 확인만 (kill 없음)
#
# 판별: CommandLine에 -m pytest 포함 AND 부모 프로세스 종료됨
# kill 순서: 자손 → 본체 → cmd.exe 부모 → sh.exe 조상 (pyenv 경로만)
# 안전: NSSM 서비스, monitorpage-*, redis, uvicorn 등은 kill 금지

param(
    [switch]$DryRun
)

# ── 안전장치 ──────────────────────────────────────────────────
$SafeNames = @(
    'nssm',
    'monitorpage-worker',
    'monitorpage-wdog-worker',
    'monitorpage-wdog-claude',
    'monitorpage-claude',
    'redis-server',
    'redis',
    'uvicorn'
)
$SafePids = @($PID)  # 현재 PowerShell 세션 보호

# ── 함수 정의 ─────────────────────────────────────────────────

function Get-DescendantTree {
    param([int]$RootId, [hashtable]$Visited = @{})
    if ($Visited.ContainsKey($RootId)) { return @() }
    $Visited[$RootId] = $true

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$RootId" -EA SilentlyContinue
    $result = @()
    foreach ($c in $children) {
        $result += Get-DescendantTree -RootId $c.ProcessId -Visited $Visited
    }
    $result += $RootId
    return $result
}

function Test-IsOrphan {
    param([int]$ProcId)
    $wmi = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcId" -EA SilentlyContinue
    if (-not $wmi) { return $false }
    $parentId = $wmi.ParentProcessId
    if (-not $parentId -or $parentId -eq 0) { return $true }
    $parent = Get-Process -Id $parentId -EA SilentlyContinue
    if (-not $parent) { return $true }
    # 부모가 NSSM 서비스면 의도적 고아 → 정상
    if ($SafeNames -contains $parent.Name) { return $false }
    return $false
}

function Get-OrphanPytestChain {
    $allProcs = Get-CimInstance Win32_Process -EA SilentlyContinue
    $orphanRoots = @()

    foreach ($p in $allProcs) {
        if (-not $p.CommandLine) { continue }
        if ($p.CommandLine -notlike '*-m pytest*') { continue }
        if (-not (Test-IsOrphan -ProcId $p.ProcessId)) { continue }
        $orphanRoots += $p.ProcessId
    }

    if ($orphanRoots.Count -eq 0) { return @() }

    $killList = @()
    $seen = @{}

    foreach ($rootId in $orphanRoots) {
        # 1. 자손 → 본체 (역순: 잎 먼저)
        $tree = Get-DescendantTree -RootId $rootId
        foreach ($id in $tree) {
            if (-not $seen.ContainsKey($id)) {
                $seen[$id] = $true
                $killList += $id
            }
        }

        # 2. 부모 cmd.exe
        $wmi = Get-CimInstance Win32_Process -Filter "ProcessId=$rootId" -EA SilentlyContinue
        if ($wmi) {
            $parentId = $wmi.ParentProcessId
            $parentWmi = Get-CimInstance Win32_Process -Filter "ProcessId=$parentId" -EA SilentlyContinue
            if ($parentWmi -and $parentWmi.Name -eq 'cmd.exe') {
                if (-not $seen.ContainsKey($parentId)) {
                    $seen[$parentId] = $true
                    $killList += $parentId
                }
                # 3. 조상 sh.exe (pyenv 경로 포함 시만)
                $gpId = $parentWmi.ParentProcessId
                $gpWmi = Get-CimInstance Win32_Process -Filter "ProcessId=$gpId" -EA SilentlyContinue
                if ($gpWmi -and $gpWmi.Name -eq 'sh.exe' -and $gpWmi.CommandLine -like '*pyenv*') {
                    if (-not $seen.ContainsKey($gpId)) {
                        $seen[$gpId] = $true
                        $killList += $gpId
                    }
                }
            }
        }
    }

    return $killList
}

# ── 메인 ──────────────────────────────────────────────────────

$targets = Get-OrphanPytestChain

if ($targets.Count -eq 0) {
    Write-Host "[ORPHAN-CLEAN] 고아 pytest 없음"
    exit 0
}

# 로그 디렉토리 준비
$logDir = "C:\tmp\orphan-cleanup"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logPath = Join-Path $logDir "$(Get-Date -Format 'yyyyMMdd_HHmmss').txt"

# 정보 수집 및 출력
$lines = @("=== 고아 프로세스 정리 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===")
$totalMemMB = 0

foreach ($id in $targets) {
    $proc = Get-Process -Id $id -EA SilentlyContinue
    $wmi  = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -EA SilentlyContinue
    $name = if ($proc) { $proc.Name } elseif ($wmi) { $wmi.Name } else { "unknown" }
    $memMB = if ($proc) { [math]::Round($proc.WorkingSet64 / 1MB, 0) } else { 0 }
    $cmd  = if ($wmi -and $wmi.CommandLine) { $wmi.CommandLine.Substring(0, [math]::Min(80, $wmi.CommandLine.Length)) } else { "" }

    # 안전장치 최종 확인
    if ($SafeNames -contains $name -or $SafePids -contains $id) {
        Write-Host "[ORPHAN-SKIP] PID=$id Name=$name (안전 목록)"
        continue
    }

    $line = "PID=$id Name=$name MemMB=$memMB CMD=$cmd"
    $lines += $line
    $totalMemMB += $memMB

    if ($DryRun) {
        Write-Host "[ORPHAN-DRYRUN] $line"
    } else {
        Write-Host "[ORPHAN-KILL] $line"
        Stop-Process -Id $id -Force -EA SilentlyContinue
    }
}

$lines | Out-File -FilePath $logPath -Encoding UTF8

if ($DryRun) {
    Write-Host "[ORPHAN-CLEAN] DryRun 완료 — 총 $($targets.Count)개 대상, 약 $([math]::Round($totalMemMB/1024,1)) GB (로그: $logPath)"
} else {
    Write-Host "[ORPHAN-CLEAN] 완료 — 총 $($targets.Count)개 kill, 약 $([math]::Round($totalMemMB/1024,1)) GB 회수 (로그: $logPath)"
}

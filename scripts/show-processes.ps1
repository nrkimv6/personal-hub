<#
.SYNOPSIS
    시스템 프로세스 실행 주체 확인 스크립트
.DESCRIPTION
    PowerShell, cmd, Python, Node, Claude Code 관련 프로세스의
    실행 주체(사용자), 부모 프로세스, 메모리 사용량을 표시합니다.
.EXAMPLE
    .\scripts\show-processes.ps1
    .\scripts\show-processes.ps1 -Filter python
    .\scripts\show-processes.ps1 -Tree
#>

param(
    [string]$Filter,    # 특정 프로세스만 필터링 (예: python, node, powershell)
    [switch]$Tree,      # 부모-자식 트리 형태로 표시
    [switch]$Summary    # 요약만 표시
)

$targetPatterns = @(
    'powershell', 'pwsh',
    'cmd',
    'python', 'monitorpage-*',
    'node', 'claude',
    'conhost', 'windowsterminal', 'wt'
)

# WMI로 프로세스 정보 수집 (Owner 포함)
$procs = Get-CimInstance Win32_Process | Where-Object {
    $name = $_.Name.ToLower()
    if ($Filter) {
        $name -like "*$($Filter.ToLower())*"
    } else {
        $targetPatterns | Where-Object { $name -like "*$_*" }
    }
} | ForEach-Object {
    $owner = try {
        $result = Invoke-CimMethod -InputObject $_ -MethodName GetOwner -ErrorAction Stop
        if ($result.User) { "$($result.Domain)\$($result.User)" } else { "SYSTEM" }
    } catch { "N/A" }

    $memMB = [math]::Round($_.WorkingSetSize / 1MB, 1)
    $cmdLine = $_.CommandLine
    # 커맨드라인 축약 (너무 길면)
    if ($cmdLine -and $cmdLine.Length -gt 120) {
        $cmdLine = $cmdLine.Substring(0, 117) + "..."
    }

    [PSCustomObject]@{
        PID       = $_.ProcessId
        PPID      = $_.ParentProcessId
        Name      = $_.Name
        Owner     = $owner
        MemMB     = $memMB
        Session   = $_.SessionId
        CmdLine   = $cmdLine
    }
}

if (-not $procs) {
    Write-Host "매칭되는 프로세스가 없습니다." -ForegroundColor Yellow
    return
}

# 세션별 구분
$session0 = $procs | Where-Object { $_.Session -eq 0 }
$sessionUser = $procs | Where-Object { $_.Session -ne 0 }

function Show-ProcessTable($items, $label) {
    if (-not $items) { return }
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    $items | Sort-Object Name, PID |
        Format-Table PID, PPID, Name, Owner, @{N='Mem(MB)';E={$_.MemMB};A='Right'},
                     @{N='CommandLine';E={$_.CmdLine}} -AutoSize -Wrap
}

if ($Tree) {
    # 트리 형태 출력
    Write-Host "`n=== 프로세스 트리 ===" -ForegroundColor Cyan
    $pidMap = @{}
    $procs | ForEach-Object { $pidMap[$_.PID] = $_ }

    # 루트 찾기 (부모가 목록에 없는 것)
    $roots = $procs | Where-Object { -not $pidMap.ContainsKey($_.PPID) }

    function Show-Tree($proc, $indent) {
        $mem = "$($proc.MemMB)MB"
        $ownerShort = ($proc.Owner -split '\\')[-1]
        Write-Host "${indent}├─ [$($proc.PID)] $($proc.Name)  ($ownerShort, $mem, Session $($proc.Session))" -ForegroundColor White
        if ($proc.CmdLine) {
            Write-Host "${indent}│    $($proc.CmdLine)" -ForegroundColor DarkGray
        }
        $children = $procs | Where-Object { $_.PPID -eq $proc.PID -and $_.PID -ne $proc.PID }
        foreach ($child in $children) {
            Show-Tree $child "${indent}│  "
        }
    }

    foreach ($root in ($roots | Sort-Object PID)) {
        Show-Tree $root ""
        Write-Host ""
    }
} else {
    Show-ProcessTable $session0 "Session 0 (NSSM 서비스 / 시스템)"
    Show-ProcessTable $sessionUser "Session 1+ (사용자 / 시작프로그램)"
}

# 메모리 요약
$totalMB = [math]::Round(($procs | Measure-Object -Property MemMB -Sum).Sum, 0)
$byName = $procs | Group-Object Name | ForEach-Object {
    [PSCustomObject]@{
        Name  = $_.Name
        Count = $_.Count
        TotalMB = [math]::Round(($_.Group | Measure-Object -Property MemMB -Sum).Sum, 0)
    }
} | Sort-Object TotalMB -Descending

Write-Host "`n=== 메모리 요약 (합계: ${totalMB}MB) ===" -ForegroundColor Green
$byName | Format-Table Name, Count, @{N='Total(MB)';E={$_.TotalMB};A='Right'} -AutoSize

# 시스템 전체 메모리
$os = Get-CimInstance Win32_OperatingSystem
$totalPhys = [math]::Round($os.TotalVisibleMemorySize / 1KB, 0)
$freeMB = [math]::Round($os.FreePhysicalMemory / 1KB, 0)
$usedMB = $totalPhys - $freeMB
$usedPct = [math]::Round($usedMB / $totalPhys * 100, 1)

Write-Host "시스템 메모리: ${usedMB}MB / ${totalPhys}MB 사용 중 (${usedPct}%)" -ForegroundColor $(if ($usedPct -gt 90) { 'Red' } elseif ($usedPct -gt 75) { 'Yellow' } else { 'Green' })

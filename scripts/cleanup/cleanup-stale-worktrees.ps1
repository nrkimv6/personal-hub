<#
.SYNOPSIS
    잔존 워크트리 및 머지 완료 브랜치 일괄 정리

.DESCRIPTION
    git worktree list --porcelain 파싱 후 main이 아닌 모든 워크트리 나열.
    각 워크트리 브랜치가 main에 머지 완료됐는지 확인 후 자동 정리.
    머지되지 않은 브랜치는 경고만 출력 (삭제 안 함).

.PARAMETER Force
    머지 여부와 관계없이 모든 stale 워크트리 강제 삭제

.PARAMETER DryRun
    실제 삭제 없이 대상 워크트리 목록만 출력

.EXAMPLE
    .\scripts\cleanup-stale-worktrees.ps1
    .\scripts\cleanup-stale-worktrees.ps1 -DryRun
    .\scripts\cleanup-stale-worktrees.ps1 -Force
#>

param(
    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectDir = "D:\work\project\tools\monitor-page"

Set-Location $ProjectDir

Write-Host "[cleanup-stale-worktrees] 워크트리 정리 시작" -ForegroundColor Cyan
if ($DryRun) { Write-Host "[DRY-RUN] 실제 삭제 없이 목록만 표시합니다." -ForegroundColor Yellow }

# git worktree list --porcelain 파싱
$raw = git worktree list --porcelain 2>&1
$worktrees = @()
$current = $null

foreach ($line in $raw) {
    if ($line -match "^worktree (.+)$") {
        if ($current) { $worktrees += $current }
        $current = @{ path = $Matches[1]; branch = ""; bare = $false }
    } elseif ($line -match "^branch (.+)$") {
        if ($current) { $current.branch = $Matches[1] }
    } elseif ($line -eq "bare") {
        if ($current) { $current.bare = $true }
    }
}
if ($current) { $worktrees += $current }

Write-Host "[cleanup-stale-worktrees] 총 워크트리 수: $($worktrees.Count)"

# main 브랜치에 머지된 브랜치 목록
$mergedBranches = git branch --merged main 2>&1 | ForEach-Object { $_.Trim().TrimStart("* ") }

$cleaned = 0
$skipped = 0
$warned = 0

foreach ($wt in $worktrees) {
    # main 워크트리(루트)는 건너뜀
    if ($wt.path -eq $ProjectDir -or $wt.branch -eq "refs/heads/main" -or $wt.bare) {
        continue
    }

    $shortBranch = $wt.branch -replace "^refs/heads/", ""
    $isMerged = $mergedBranches -contains $shortBranch

    if ($isMerged -or $Force) {
        $tag = if ($isMerged) { "MERGED" } else { "FORCE" }
        Write-Host "[$tag] 정리 대상: $($wt.path) (branch: $shortBranch)" -ForegroundColor $(if ($isMerged) { "Green" } else { "Magenta" })

        if (-not $DryRun) {
            # worktree 제거
            git worktree remove $wt.path --force 2>&1 | Out-Null
            # 브랜치 삭제
            git branch -D $shortBranch 2>&1 | Out-Null
            Write-Host "  → 삭제 완료" -ForegroundColor DarkGray
            $cleaned++
        } else {
            Write-Host "  → [DRY-RUN] 삭제 예정" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "[WARN] 미머지 브랜치 — 건너뜀: $($wt.path) (branch: $shortBranch)" -ForegroundColor Yellow
        $warned++
        $skipped++
    }
}

Write-Host ""
Write-Host "[cleanup-stale-worktrees] 완료 — 정리: $cleaned, 스킵: $skipped, 경고: $warned" -ForegroundColor Cyan
if ($warned -gt 0) {
    Write-Host "  미머지 브랜치 강제 삭제: .\scripts\cleanup-stale-worktrees.ps1 -Force" -ForegroundColor DarkYellow
}

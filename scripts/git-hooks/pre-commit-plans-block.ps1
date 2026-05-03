# pre-commit-plans-block.ps1
#
# 목적: plans lineage가 아닌 checkout에서 docs/plan, docs/archive staged commit을 차단한다.
#
# --no-verify 사용 절대 금지

function Get-HookValue {
    param(
        [string]$Name,
        [scriptblock]$Fallback
    )

    if ($env:PLAN_HOOK_DRY_RUN -eq "1") {
        $override = Get-Item -Path "Env:$Name" -ErrorAction SilentlyContinue
        if ($null -ne $override) {
            return $override.Value
        }
    }

    return & $Fallback
}

function ConvertTo-HookBool {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    return @("1", "true", "yes", "on") -contains $Value.Trim().ToLowerInvariant()
}

function Get-NormalizedPath {
    param([string]$PathValue)

    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        return $null
    }

    try {
        return [System.IO.Path]::GetFullPath($PathValue).TrimEnd('\', '/').Replace('\', '/')
    } catch {
        return $PathValue.TrimEnd('\', '/').Replace('\', '/')
    }
}

function Test-GitRefExists {
    param([string]$Ref)

    if ($env:PLAN_HOOK_DRY_RUN -eq "1") {
        switch ($Ref) {
            "refs/heads/plans" { return ConvertTo-HookBool $env:PLAN_HOOK_HAS_LOCAL_PLANS_REF }
            "refs/remotes/origin/plans" { return ConvertTo-HookBool $env:PLAN_HOOK_HAS_REMOTE_PLANS_REF }
            default { return $false }
        }
    }

    git show-ref --verify --quiet $Ref 2>$null
    return $LASTEXITCODE -eq 0
}

function Test-PlansMergeBase {
    param([string]$Ref)

    if ($env:PLAN_HOOK_DRY_RUN -eq "1") {
        switch ($Ref) {
            "refs/heads/plans" { return ConvertTo-HookBool $env:PLAN_HOOK_LOCAL_PLANS_MERGEBASABLE }
            "refs/remotes/origin/plans" { return ConvertTo-HookBool $env:PLAN_HOOK_REMOTE_PLANS_MERGEBASABLE }
            default { return $false }
        }
    }

    git merge-base HEAD $Ref 2>$null | Out-Null
    return $LASTEXITCODE -eq 0
}

function Test-IsPlansLineage {
    param(
        [string]$Branch,
        [string]$RepoRoot
    )

    $commonGitDir = Get-HookValue -Name "PLAN_HOOK_COMMON_GIT_DIR" -Fallback { git rev-parse --git-common-dir 2>$null }
    $projectRoot = $null
    if (-not [string]::IsNullOrWhiteSpace($commonGitDir)) {
        $commonGitPath = $commonGitDir
        if (-not [System.IO.Path]::IsPathRooted($commonGitPath) -and -not [string]::IsNullOrWhiteSpace($RepoRoot)) {
            $commonGitPath = Join-Path $RepoRoot $commonGitPath
        }
        $projectRoot = Get-NormalizedPath (Split-Path -Parent $commonGitPath)
    }

    $normalizedRepoRoot = Get-NormalizedPath $RepoRoot
    if ([string]::IsNullOrWhiteSpace($normalizedRepoRoot) -or [string]::IsNullOrWhiteSpace($projectRoot)) {
        return [pscustomobject]@{
            Allowed = $false
            Reason = "missing_worktree_context"
            RefSource = $null
            RepoRoot = $normalizedRepoRoot
            ProjectRoot = $projectRoot
        }
    }

    if ($normalizedRepoRoot -eq $projectRoot) {
        return [pscustomobject]@{
            Allowed = $false
            Reason = "disallowed_worktree"
            RefSource = "project-root"
            RepoRoot = $normalizedRepoRoot
            ProjectRoot = $projectRoot
        }
    }

    $candidateRefs = @()
    if (Test-GitRefExists "refs/heads/plans") {
        $candidateRefs += [pscustomobject]@{
            Ref = "refs/heads/plans"
            Label = "local plans branch"
        }
    }
    if (Test-GitRefExists "refs/remotes/origin/plans") {
        $candidateRefs += [pscustomobject]@{
            Ref = "refs/remotes/origin/plans"
            Label = "origin/plans"
        }
    }

    if ($candidateRefs.Count -eq 0) {
        return [pscustomobject]@{
            Allowed = $false
            Reason = "missing_plans_ref"
            RefSource = $null
            RepoRoot = $normalizedRepoRoot
            ProjectRoot = $projectRoot
        }
    }

    foreach ($candidate in $candidateRefs) {
        if (Test-PlansMergeBase $candidate.Ref) {
            return [pscustomobject]@{
                Allowed = $true
                Reason = "plans_lineage"
                RefSource = $candidate.Label
                RepoRoot = $normalizedRepoRoot
                ProjectRoot = $projectRoot
            }
        }
    }

    return [pscustomobject]@{
        Allowed = $false
        Reason = "non_plans_lineage"
        RefSource = ($candidateRefs.Label -join ", ")
        RepoRoot = $normalizedRepoRoot
        ProjectRoot = $projectRoot
    }
}

$stagedRaw = Get-HookValue -Name "PLAN_HOOK_STAGED" -Fallback { git diff --cached --name-only 2>$null }
$branch = Get-HookValue -Name "PLAN_HOOK_BRANCH" -Fallback { git rev-parse --abbrev-ref HEAD 2>$null }
$repoRoot = Get-HookValue -Name "PLAN_HOOK_REPO_ROOT" -Fallback { git rev-parse --show-toplevel 2>$null }

$staged = @($stagedRaw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$planFiles = @($staged | Where-Object { $_ -match "^docs/(plan|archive)/" })
if ($planFiles.Count -eq 0) {
    exit 0
}

$lineage = Test-IsPlansLineage -Branch $branch -RepoRoot $repoRoot
if ($lineage.Allowed) {
    exit 0
}

$reasonText = switch ($lineage.Reason) {
    "disallowed_worktree" { "project root checkout에서는 docs/plan, docs/archive 커밋을 허용하지 않습니다." }
    "missing_worktree_context" { "현재 checkout 경로 또는 공용 git dir를 판정하지 못해 safe-fail 차단합니다." }
    "missing_plans_ref" { "local plans branch 또는 origin/plans ref를 찾지 못해 safe-fail 차단합니다." }
    "non_plans_lineage" { "현재 checkout은 plans lineage가 아닙니다." }
    default { "허용되지 않은 checkout입니다." }
}

Write-Warning "⚠️  [pre-commit hook] docs/plan 또는 docs/archive staged 변경은 plans lineage worktree에서만 허용됩니다."
Write-Warning "    차단 사유: $($lineage.Reason)"
Write-Warning "    설명: $reasonText"
Write-Warning "    현재 브랜치: $branch"
Write-Warning "    현재 checkout: $($lineage.RepoRoot)"
Write-Warning "    project root: $($lineage.ProjectRoot)"
if (-not [string]::IsNullOrWhiteSpace($lineage.RefSource)) {
    Write-Warning "    plans 판정 기준: $($lineage.RefSource)"
}
Write-Warning "    staged plan/archive files:"
$planFiles | ForEach-Object { Write-Warning "      - $_" }
Write-Warning "    우회 금지: --no-verify"
Write-Warning "    해결 방법: .worktrees/plans 또는 plans lineage 기반 비-root sync worktree에서 다시 커밋하세요."

exit 1

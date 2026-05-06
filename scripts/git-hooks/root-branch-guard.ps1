param(
    [ValidateSet("Commit", "Status", "PostCheckout")]
    [string]$Mode = "Status"
)

$ErrorActionPreference = "Stop"

function Get-GuardValue {
    param(
        [string]$Name,
        [scriptblock]$Fallback
    )

    if ($env:ROOT_GUARD_DRY_RUN -eq "1") {
        $override = Get-Item -Path "Env:$Name" -ErrorAction SilentlyContinue
        if ($null -ne $override) {
            return $override.Value
        }
    }
    return & $Fallback
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

function ConvertTo-RelativeGitPath {
    param([string]$PathValue)
    return $PathValue.Trim().Replace('\', '/')
}

function Get-ProjectRootFromCommonGitDir {
    param(
        [string]$RepoRoot,
        [string]$CommonGitDir
    )

    if ([string]::IsNullOrWhiteSpace($CommonGitDir)) {
        return $null
    }
    $commonPath = $CommonGitDir
    if (-not [System.IO.Path]::IsPathRooted($commonPath) -and -not [string]::IsNullOrWhiteSpace($RepoRoot)) {
        $commonPath = Join-Path $RepoRoot $commonPath
    }
    return Get-NormalizedPath (Split-Path -Parent $commonPath)
}

function Get-StagedPaths {
    $raw = Get-GuardValue -Name "ROOT_GUARD_STAGED" -Fallback { git diff --cached --name-only 2>$null }
    return @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { ConvertTo-RelativeGitPath $_ })
}

function Get-StatusPorcelain {
    $raw = Get-GuardValue -Name "ROOT_GUARD_STATUS" -Fallback { git status --porcelain=v1 2>$null }
    return @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Test-MirrorSurfacePath {
    param([string]$PathValue)

    $p = ConvertTo-RelativeGitPath $PathValue
    return (
        $p -match "^\.agents/" -or
        $p -match "^\.agent/" -or
        $p -match "^\.claude/" -or
        $p -match "^\.gemini/"
    )
}

function Test-AllowedRootCommitPath {
    param([string]$PathValue)

    $p = ConvertTo-RelativeGitPath $PathValue
    if ($p -in @("MANUAL_TASKS.md", "CHANGELOG.md")) {
        return $true
    }
    if ($p -match "^docs/(archive/|plan/)") {
        return $true
    }
    return $false
}

function Get-RepoContext {
    $repoRoot = Get-NormalizedPath (Get-GuardValue -Name "ROOT_GUARD_REPO_ROOT" -Fallback { git rev-parse --show-toplevel 2>$null })
    $branch = (Get-GuardValue -Name "ROOT_GUARD_BRANCH" -Fallback { git rev-parse --abbrev-ref HEAD 2>$null }).Trim()
    $commonGitDir = Get-GuardValue -Name "ROOT_GUARD_COMMON_GIT_DIR" -Fallback { git rev-parse --git-common-dir 2>$null }
    $projectRoot = Get-NormalizedPath (Get-GuardValue -Name "ROOT_GUARD_PROJECT_ROOT" -Fallback { Get-ProjectRootFromCommonGitDir -RepoRoot $repoRoot -CommonGitDir $commonGitDir })

    $isRootCheckout = (
        -not [string]::IsNullOrWhiteSpace($repoRoot) -and
        -not [string]::IsNullOrWhiteSpace($projectRoot) -and
        $repoRoot -eq $projectRoot
    )

    $sentinel = Get-GuardValue -Name "ROOT_GUARD_SENTINEL" -Fallback {
        if ([string]::IsNullOrWhiteSpace($projectRoot)) {
            return $null
        }
        return (Join-Path (Join-Path $projectRoot ".git") "root-branch-guard.violation")
    }

    return [pscustomobject]@{
        RepoRoot = $repoRoot
        ProjectRoot = $projectRoot
        Branch = $branch
        IsRootCheckout = $isRootCheckout
        Sentinel = $sentinel
    }
}

function Write-Context {
    param([object]$Context)
    Write-Output "mode=$Mode"
    Write-Output "repo_root=$($Context.RepoRoot)"
    Write-Output "project_root=$($Context.ProjectRoot)"
    Write-Output "branch=$($Context.Branch)"
    Write-Output "is_root_checkout=$($Context.IsRootCheckout)"
    Write-Output "sentinel=$($Context.Sentinel)"
}

$context = Get-RepoContext

if ($Mode -eq "Status") {
    Write-Context $context
    exit 0
}

if ($Mode -eq "Commit") {
    $staged = Get-StagedPaths
    $mirrorBlocked = @($staged | Where-Object { Test-MirrorSurfacePath $_ })
    if ($mirrorBlocked.Count -gt 0) {
        Write-Error "mirror_surface_direct_edit_blocked: mirror surfaces are generated from wtools sync and must not be committed locally."
        Write-Error "Use wtools source changes, then receive the remote sync commit with git pull --ff-only."
        Write-Error "blocked staged files:"
        $mirrorBlocked | ForEach-Object { Write-Error "  - $_" }
        exit 1
    }
}

if (-not $context.IsRootCheckout) {
    exit 0
}

if ($Mode -eq "PostCheckout") {
    if ($context.Branch -ne "main") {
        if (-not [string]::IsNullOrWhiteSpace($context.Sentinel)) {
            $parent = Split-Path -Parent $context.Sentinel
            if (-not (Test-Path -LiteralPath $parent)) {
                New-Item -ItemType Directory -Path $parent -Force | Out-Null
            }
            @(
                "root_branch_guard_violation",
                "branch=$($context.Branch)",
                "repo_root=$($context.RepoRoot)",
                "created_at=$(Get-Date -Format o)"
            ) | Set-Content -LiteralPath $context.Sentinel -Encoding UTF8
        }
        Write-Error "root_branch_guard_violation: root checkout moved off main (branch=$($context.Branch)). Return root to main before continuing."
        exit 1
    }
    exit 0
}

if ($Mode -eq "Commit") {
    if ($context.Branch -ne "main") {
        Write-Error "root_branch_guard_blocked: root checkout commits are allowed only on main (branch=$($context.Branch))."
        exit 1
    }

    if (-not [string]::IsNullOrWhiteSpace($context.Sentinel) -and (Test-Path -LiteralPath $context.Sentinel)) {
        Write-Error "root_branch_guard_sentinel: $($context.Sentinel) exists. Verify root branch recovery before committing."
        exit 1
    }

    $blocked = @($staged | Where-Object { -not (Test-AllowedRootCommitPath $_) })
    if ($blocked.Count -gt 0) {
        Write-Error "root_worktree_impl_scope_blocked: root main worktree cannot commit implementation-scope files directly. Use an impl worktree."
        Write-Error "blocked staged files:"
        $blocked | ForEach-Object { Write-Error "  - $_" }
        exit 1
    }
}

exit 0

param(
    [switch]$AsLibrary
)

function Import-RootWorktreeContract {
    param([string]$Path)

    $psDataLoader = Get-Command -Name "Import-PowerShellDataFile" -ErrorAction SilentlyContinue
    if ($null -ne $psDataLoader) {
        return Import-PowerShellDataFile -Path $Path
    }

    # Git hook hosts can miss Import-PowerShellDataFile; fall back to evaluating
    # the local psd1 expression directly so the allowlist contract still loads.
    $raw = Get-Content -LiteralPath $Path -Raw
    return & ([scriptblock]::Create($raw))
}

$script:RootWorktreeContract = Import-RootWorktreeContract -Path (Join-Path $PSScriptRoot "root-worktree-contract.psd1")

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

function Get-RootWorktreeGuardContext {
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
    $isRootWorktree = (
        -not [string]::IsNullOrWhiteSpace($normalizedRepoRoot) -and
        -not [string]::IsNullOrWhiteSpace($projectRoot) -and
        $normalizedRepoRoot -eq $projectRoot
    )

    return [pscustomobject]@{
        Branch = $Branch
        RepoRoot = $normalizedRepoRoot
        ProjectRoot = $projectRoot
        IsRootWorktree = $isRootWorktree
        IsMainBranch = ($Branch -eq "main")
    }
}

function Get-RootWorktreeAllowPatterns {
    return @($script:RootWorktreeContract.RootWorktreeAllowPatterns)
}

function Get-ImplementationScopeExamples {
    return @($script:RootWorktreeContract.ImplementationScopeExamples)
}

function Test-IsAllowedRootWorktreePath {
    param([string]$PathValue)

    $normalized = if ($null -eq $PathValue) { "" } else { $PathValue }
    $normalized = $normalized.Trim().Replace('\', '/')
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $true
    }

    foreach ($pattern in (Get-RootWorktreeAllowPatterns)) {
        if ($normalized -match $pattern) {
            return $true
        }
    }
    return $false
}

function Invoke-PreCommitRootWorktreeBlock {
    $stagedRaw = Get-HookValue -Name "PLAN_HOOK_STAGED" -Fallback { git diff --cached --name-only 2>$null }
    $branch = Get-HookValue -Name "PLAN_HOOK_BRANCH" -Fallback { git rev-parse --abbrev-ref HEAD 2>$null }
    $repoRoot = Get-HookValue -Name "PLAN_HOOK_REPO_ROOT" -Fallback { git rev-parse --show-toplevel 2>$null }

    $staged = @($stagedRaw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $context = Get-RootWorktreeGuardContext -Branch $branch -RepoRoot $repoRoot
    if (-not $context.IsRootWorktree) {
        return [pscustomobject]@{
            Allowed = $true
            ExitCode = 0
            Reason = "non_root_worktree"
            Context = $context
            BlockedPaths = @()
        }
    }

    $blockedPaths = @($staged | Where-Object { -not (Test-IsAllowedRootWorktreePath $_) })
    if ($blockedPaths.Count -eq 0) {
        return [pscustomobject]@{
            Allowed = $true
            ExitCode = 0
            Reason = "allowlisted_root_paths_only"
            Context = $context
            BlockedPaths = @()
        }
    }

    Write-Warning "⚠️  [pre-commit hook] root worktree에서 implementation-scope staged 변경은 허용되지 않습니다."
    Write-Warning "    차단 사유: root_worktree_impl_scope_blocked"
    Write-Warning "    현재 브랜치: $($context.Branch)"
    Write-Warning "    현재 checkout: $($context.RepoRoot)"
    Write-Warning "    project root: $($context.ProjectRoot)"
    if ($context.IsMainBranch) {
        Write-Warning "    분류: root main worktree"
    } else {
        Write-Warning "    분류: root non-main worktree"
    }
    Write-Warning "    허용 경로: TODO.md, docs/DONE.md, docs/plan/*, docs/archive/*, .worktrees/impl-*, .worktrees/plans"
    Write-Warning "    구현성 경로 예시: $((Get-ImplementationScopeExamples) -join ', ')"
    Write-Warning "    차단된 staged paths:"
    $blockedPaths | ForEach-Object { Write-Warning "      - $_" }
    Write-Warning "    해결 방법: 현재 작업용 impl worktree 또는 대상 repo worktree에서 다시 커밋하세요."
    Write-Warning "    우회 금지: --no-verify"

    return [pscustomobject]@{
        Allowed = $false
        ExitCode = 1
        Reason = "root_worktree_impl_scope_blocked"
        Context = $context
        BlockedPaths = $blockedPaths
    }
}

if (-not $AsLibrary) {
    $result = Invoke-PreCommitRootWorktreeBlock
    exit $result.ExitCode
}

param()

$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$hookPath = Join-Path $projectRoot "scripts\git-hooks\pre-commit-plans-block.ps1"
$commonGitDir = Join-Path $projectRoot ".git"

function Invoke-HookDryRunCase {
    param(
        [hashtable]$Case
    )

    $managedKeys = @(
        "PLAN_HOOK_DRY_RUN",
        "PLAN_HOOK_STAGED",
        "PLAN_HOOK_BRANCH",
        "PLAN_HOOK_REPO_ROOT",
        "PLAN_HOOK_COMMON_GIT_DIR",
        "PLAN_HOOK_HAS_LOCAL_PLANS_REF",
        "PLAN_HOOK_HAS_REMOTE_PLANS_REF",
        "PLAN_HOOK_LOCAL_PLANS_MERGEBASABLE",
        "PLAN_HOOK_REMOTE_PLANS_MERGEBASABLE"
    )

    $backup = @{}
    foreach ($key in $managedKeys) {
        $current = Get-Item -Path "Env:$key" -ErrorAction SilentlyContinue
        $backup[$key] = if ($null -eq $current) { $null } else { $current.Value }
        Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
    }

    try {
        $env:PLAN_HOOK_DRY_RUN = "1"
        foreach ($key in $Case.Env.Keys) {
            Set-Item -Path "Env:$key" -Value $Case.Env[$key]
        }

        $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $hookPath 2>&1
        $exitCode = $LASTEXITCODE
        $outputText = ($output | ForEach-Object { "$_" }) -join "`n"

        if ($exitCode -ne $Case.ExpectExit) {
            throw "expected exit $($Case.ExpectExit), got $exitCode"
        }

        if ($Case.ContainsKey("ExpectReason") -and $outputText -notmatch [regex]::Escape($Case.ExpectReason)) {
            throw "expected reason '$($Case.ExpectReason)' not found in output"
        }

        return [pscustomobject]@{
            Case = $Case.Name
            ExitCode = $exitCode
            Result = "PASS"
            Reason = if ($Case.ContainsKey("ExpectReason")) { $Case.ExpectReason } else { "allowed" }
        }
    } finally {
        foreach ($key in $managedKeys) {
            Remove-Item -Path "Env:$key" -ErrorAction SilentlyContinue
            if ($null -ne $backup[$key]) {
                Set-Item -Path "Env:$key" -Value $backup[$key]
            }
        }
    }
}

$cases = @(
    @{
        Name = "allow_local_plans_worktree"
        ExpectExit = 0
        Env = @{
            PLAN_HOOK_STAGED = "docs/archive/smoke.md"
            PLAN_HOOK_BRANCH = "plans"
            PLAN_HOOK_REPO_ROOT = (Join-Path $projectRoot ".worktrees\plans")
            PLAN_HOOK_COMMON_GIT_DIR = $commonGitDir
            PLAN_HOOK_HAS_LOCAL_PLANS_REF = "1"
            PLAN_HOOK_LOCAL_PLANS_MERGEBASABLE = "1"
            PLAN_HOOK_HAS_REMOTE_PLANS_REF = "1"
            PLAN_HOOK_REMOTE_PLANS_MERGEBASABLE = "1"
        }
    },
    @{
        Name = "allow_origin_sync_worktree"
        ExpectExit = 0
        Env = @{
            PLAN_HOOK_STAGED = "docs/archive/smoke.md"
            PLAN_HOOK_BRANCH = "codex/plans-sync"
            PLAN_HOOK_REPO_ROOT = (Join-Path $projectRoot ".worktrees\plans-sync")
            PLAN_HOOK_COMMON_GIT_DIR = $commonGitDir
            PLAN_HOOK_HAS_LOCAL_PLANS_REF = "0"
            PLAN_HOOK_HAS_REMOTE_PLANS_REF = "1"
            PLAN_HOOK_REMOTE_PLANS_MERGEBASABLE = "1"
        }
    },
    @{
        Name = "block_project_root_checkout"
        ExpectExit = 1
        ExpectReason = "disallowed_worktree"
        Env = @{
            PLAN_HOOK_STAGED = "docs/archive/smoke.md"
            PLAN_HOOK_BRANCH = "main"
            PLAN_HOOK_REPO_ROOT = $projectRoot
            PLAN_HOOK_COMMON_GIT_DIR = $commonGitDir
            PLAN_HOOK_HAS_LOCAL_PLANS_REF = "1"
            PLAN_HOOK_LOCAL_PLANS_MERGEBASABLE = "1"
        }
    },
    @{
        Name = "block_non_plans_lineage_worktree"
        ExpectExit = 1
        ExpectReason = "non_plans_lineage"
        Env = @{
            PLAN_HOOK_STAGED = "docs/plan/smoke.md"
            PLAN_HOOK_BRANCH = "impl/non-plans"
            PLAN_HOOK_REPO_ROOT = (Join-Path $projectRoot ".worktrees\impl-non-plans")
            PLAN_HOOK_COMMON_GIT_DIR = $commonGitDir
            PLAN_HOOK_HAS_LOCAL_PLANS_REF = "1"
            PLAN_HOOK_LOCAL_PLANS_MERGEBASABLE = "0"
            PLAN_HOOK_HAS_REMOTE_PLANS_REF = "1"
            PLAN_HOOK_REMOTE_PLANS_MERGEBASABLE = "0"
        }
    },
    @{
        Name = "block_missing_plans_refs"
        ExpectExit = 1
        ExpectReason = "missing_plans_ref"
        Env = @{
            PLAN_HOOK_STAGED = "docs/archive/smoke.md"
            PLAN_HOOK_BRANCH = "codex/plans-sync"
            PLAN_HOOK_REPO_ROOT = (Join-Path $projectRoot ".worktrees\plans-sync")
            PLAN_HOOK_COMMON_GIT_DIR = $commonGitDir
            PLAN_HOOK_HAS_LOCAL_PLANS_REF = "0"
            PLAN_HOOK_HAS_REMOTE_PLANS_REF = "0"
        }
    }
)

$results = @()
foreach ($case in $cases) {
    try {
        $results += Invoke-HookDryRunCase -Case $case
    } catch {
        $results += [pscustomobject]@{
            Case = $case.Name
            ExitCode = "ERR"
            Result = "FAIL"
            Reason = $_.Exception.Message
        }
    }
}

$results | Format-Table -AutoSize

if ($results.Result -contains "FAIL") {
    exit 1
}

exit 0

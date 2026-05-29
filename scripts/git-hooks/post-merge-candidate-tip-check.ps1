param(
    [string]$SquashMerge = ""
)

$ErrorActionPreference = "Stop"

$script = Join-Path (Split-Path -Parent $PSScriptRoot) "diagnostics\check-candidate-tip.ps1"
if (-not (Test-Path -LiteralPath $script)) {
    exit 0
}

try {
    git rev-parse --verify ORIG_HEAD 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        exit 0
    }

    $json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -CurrentMain ORIG_HEAD -CandidateTip HEAD -Mode PostMergeRepair
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        [Console]::Error.WriteLine("post_merge_candidate_tip_check_failed: check-candidate-tip exited $code")
        exit 0
    }
    $result = $json | ConvertFrom-Json
    $blockers = @($result.blockers)
    $mergeCommits = @($result.merge_commits)
    $repairable = @($result.repairable_merge_commits)
    $sentinel = git rev-parse --git-path candidate-tip-violation.json

    if (Test-Path -LiteralPath $sentinel) {
        $sentinelText = Get-Content -LiteralPath $sentinel -Raw -ErrorAction SilentlyContinue
        if ($sentinelText) {
            try {
                $sentinelJson = $sentinelText | ConvertFrom-Json
                if ($sentinelJson.candidate_tip -ne $result.candidate_tip) {
                    Remove-Item -LiteralPath $sentinel -Force
                }
            } catch {
                Remove-Item -LiteralPath $sentinel -Force
            }
        }
    }

    if ($repairable.Count -gt 0) {
        $head = (git rev-parse --verify HEAD).Trim()
        $orig = (git rev-parse --verify ORIG_HEAD).Trim()
        $parentLine = (git show -s --format=%P HEAD).Trim()
        $parents = @($parentLine -split "\s+" | Where-Object { $_ })
        $candidateParent = if ($parents.Count -eq 2) { $parents[1] } else { "" }
        $cleanWorktree = $true
        git diff --quiet HEAD -- 2>$null
        if ($LASTEXITCODE -ne 0) { $cleanWorktree = $false }
        git diff --cached --quiet 2>$null
        if ($LASTEXITCODE -ne 0) { $cleanWorktree = $false }
        $sameTree = $false
        if ($candidateParent) {
            git diff --quiet HEAD $candidateParent -- 2>$null
            $sameTree = $LASTEXITCODE -eq 0
        }
        if ($cleanWorktree -and $parents.Count -eq 2 -and $parents[0] -eq $orig -and $sameTree) {
            git update-ref -m "linearize post-merge candidate tip" HEAD $candidateParent $head
            if ($LASTEXITCODE -eq 0) {
                if (Test-Path -LiteralPath $sentinel) {
                    Remove-Item -LiteralPath $sentinel -Force
                }
                [pscustomobject]@{
                    status = "linearization_applied"
                    merge_commit = $head
                    new_head = $candidateParent
                    base_parent = $orig
                } | ConvertTo-Json -Depth 4 | Write-Output
                exit 0
            }
        }

        $repairRequired = [pscustomobject]@{
            status = "repair_required"
            reason = "reset_hard_free_linearization_unavailable"
            candidate_tip = $result.candidate_tip
            merge_commits = @($mergeCommits)
            repairable_merge_commits = @($repairable)
        } | ConvertTo-Json -Depth 8
        $repairRequired | Set-Content -LiteralPath $sentinel -Encoding UTF8
        [Console]::Error.WriteLine("post_merge_candidate_tip_repair_required: sentinel=$sentinel")
        exit 0
    }

    if ($mergeCommits.Count -gt 0) {
        $repairRequired = [pscustomobject]@{
            status = "repair_required"
            reason = "merge_commit_not_linearizable"
            candidate_tip = $result.candidate_tip
            merge_commits = @($mergeCommits)
            repairable_merge_commits = @($repairable)
        } | ConvertTo-Json -Depth 8
        $repairRequired | Set-Content -LiteralPath $sentinel -Encoding UTF8
        [Console]::Error.WriteLine("post_merge_candidate_tip_repair_required: sentinel=$sentinel")
        exit 0
    }

    if ($blockers.Count -gt 0) {
        $json | Set-Content -LiteralPath $sentinel -Encoding UTF8
        [Console]::Error.WriteLine("post_merge_candidate_tip_violation: blockers=$($blockers -join ', ') sentinel=$sentinel")
    }
} catch {
    [Console]::Error.WriteLine("post_merge_candidate_tip_check_error: $($_.Exception.Message)")
}

exit 0

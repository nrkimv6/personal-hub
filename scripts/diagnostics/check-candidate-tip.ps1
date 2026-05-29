param(
    [Parameter(Mandatory = $true)]
    [string]$CurrentMain,
    [Parameter(Mandatory = $true)]
    [string]$CandidateTip,
    [string]$BaseRef = "",
    [ValidateSet("Receive", "PostMergeRepair")]
    [string]$Mode = "Receive"
)

$ErrorActionPreference = "Stop"

function Invoke-GitLines {
    param([string[]]$GitArgs)
    $output = & git @GitArgs 2>$null
    if ($LASTEXITCODE -ne 0) {
        return @()
    }
    return @($output -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Invoke-GitOne {
    param([string[]]$GitArgs)
    $lines = @(Invoke-GitLines $GitArgs)
    if ($lines.Count -eq 0) { return "" }
    return $lines[0].Trim()
}

function Test-Ancestor {
    param([string]$Ancestor, [string]$Descendant)
    & git merge-base --is-ancestor $Ancestor $Descendant 2>$null
    return $LASTEXITCODE -eq 0
}

function Get-ChangedPaths {
    param([string]$Range)
    $lines = @(Invoke-GitLines @("diff", "--name-only", $Range))
    $paths = foreach ($line in $lines) {
        $path = $line.Trim().Replace("\", "/")
        if ($path) { $path }
    }
    return @($paths)
}

function Test-MirrorPath {
    param([string]$Path)
    return $Path -match "^\.agents/" -or $Path -match "^\.agent/" -or $Path -match "^\.claude/" -or $Path -match "^\.gemini/"
}

$current = Invoke-GitOne @("rev-parse", "--verify", $CurrentMain)
$candidate = Invoke-GitOne @("rev-parse", "--verify", $CandidateTip)
if ([string]::IsNullOrWhiteSpace($current) -or [string]::IsNullOrWhiteSpace($candidate)) {
    throw "unable to resolve CurrentMain=$CurrentMain or CandidateTip=$CandidateTip"
}

$mergeBase = if ([string]::IsNullOrWhiteSpace($BaseRef)) {
    Invoke-GitOne @("merge-base", $current, $candidate)
} else {
    Invoke-GitOne @("rev-parse", "--verify", $BaseRef)
}
$currentMainIsAncestor = Test-Ancestor $current $candidate

$incomingCommits = @(Invoke-GitLines @("rev-list", "--reverse", "$current..$candidate"))
$mergeCommits = @(Invoke-GitLines @("rev-list", "--merges", "--reverse", "$current..$candidate"))
$changedPaths = Get-ChangedPaths "$current..$candidate"
$candidateSidePaths = if ($mergeBase) { Get-ChangedPaths "$mergeBase..$candidate" } else { @() }
$mainSidePaths = if ($mergeBase) { Get-ChangedPaths "$mergeBase..$current" } else { @() }
$mirrorPaths = @($changedPaths | Where-Object { Test-MirrorPath $_ } | Sort-Object -Unique)

$duplicates = @()
foreach ($line in Invoke-GitLines @("cherry", "-v", $current, $candidate)) {
    if ($line -match "^\-\s+([0-9a-fA-F]+)\s*(.*)$") {
        $hash = $Matches[1]
        $subject = $Matches[2].Trim()
        $pathLines = @(Invoke-GitLines @("show", "--format=", "--name-only", $hash))
        $paths = foreach ($pathLine in $pathLines) {
            $path = $pathLine.Trim().Replace("\", "/")
            if ($path) { $path }
        }
        $patchIdLine = Invoke-GitLines @("show", $hash, "--pretty=format:", "--patch") | git patch-id --stable 2>$null
        $patchId = ""
        if ($LASTEXITCODE -eq 0 -and $patchIdLine) {
            $patchId = (($patchIdLine -split "`r?`n")[0] -split "\s+")[0]
        }
        $duplicates += [pscustomobject]@{
            commit = $hash
            subject = $subject
            patch_id = $patchId
            paths = @($paths)
        }
    }
}

$overlap = @($candidateSidePaths | Where-Object { $mainSidePaths -contains $_ } | Sort-Object -Unique)
$denominator = [Math]::Max(1, @($candidateSidePaths | Sort-Object -Unique).Count)
$overlapRatio = [Math]::Round($overlap.Count / $denominator, 4)
$pathOverlapSuspects = @()
if ($overlap.Count -gt 0) {
    $pathOverlapSuspects += [pscustomobject]@{
        ratio = $overlapRatio
        overlap_paths = @($overlap)
        candidate_path_count = $denominator
        main_path_count = @($mainSidePaths | Sort-Object -Unique).Count
    }
}

$mergeParents = @()
$repairableMergeCommits = @()
foreach ($mergeCommit in $mergeCommits) {
    $parentLine = Invoke-GitOne @("show", "-s", "--format=%P", $mergeCommit)
    $parents = @($parentLine -split "\s+" | Where-Object { $_ })
    $parentSummary = @()
    foreach ($parent in $parents) {
        $parentSummary += [pscustomobject]@{
            commit = $parent
            current_main_is_ancestor = (Test-Ancestor $current $parent)
            parent_is_ancestor_of_current_main = (Test-Ancestor $parent $current)
        }
    }
    $mergeParents += [pscustomobject]@{
        commit = $mergeCommit
        parents = @($parentSummary)
    }
    if ($Mode -eq "PostMergeRepair" -and $parents.Count -eq 2) {
        $firstParent = $parents[0]
        $candidateParent = $parents[1]
        if ($firstParent -eq $current -and (Test-Ancestor $current $candidateParent)) {
            $repairableMergeCommits += [pscustomobject]@{
                commit = $mergeCommit
                base_parent = $firstParent
                candidate_parent = $candidateParent
                repair = "linearize_to_candidate_parent"
            }
        }
    }
}

$blockers = @()
if (-not $currentMainIsAncestor) { $blockers += "stale_ancestry_blocked" }
if ($duplicates.Count -gt 0) { $blockers += "duplicate_patch_blocked" }
if ($Mode -eq "Receive" -and $mergeCommits.Count -gt 0) { $blockers += "incoming_merge_commit_blocked" }

[pscustomobject]@{
    current_main = $current
    candidate_tip = $candidate
    merge_base = $mergeBase
    current_main_is_ancestor = $currentMainIsAncestor
    incoming_commits = @($incomingCommits)
    incoming_count = $incomingCommits.Count
    merge_commits = @($mergeCommits)
    merge_parents = @($mergeParents)
    repairable_merge_commits = @($repairableMergeCommits)
    mode = $Mode
    changed_paths = @($changedPaths)
    mirror_paths = @($mirrorPaths)
    duplicates = @($duplicates)
    path_overlap_suspects = @($pathOverlapSuspects)
    blockers = @($blockers)
} | ConvertTo-Json -Depth 8

param(
    [Parameter(Mandatory = $true)]
    [string]$Candidate,
    [string]$Remote = "origin",
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"

function Invoke-GitOne {
    param([string[]]$GitArgs)
    $output = & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "git $($GitArgs -join ' ') failed"
    }
    return (($output -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First 1).Trim()
}

$repoRoot = (git rev-parse --show-toplevel).Trim()
$currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
if ($currentBranch -ne "main") {
    throw "receive-main-candidate requires root main checkout; current branch=$currentBranch"
}

git fetch $Remote $Branch
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$tuple = (Invoke-GitOne @("rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD")) -split "\s+"
$left = [int]$tuple[0]
$right = [int]$tuple[1]

if ($right -gt 0 -and $left -eq 0) {
    [Console]::Error.WriteLine("remote_receive_required: local main is behind $Remote/$Branch; run pull-main-guarded.ps1 first")
    exit 2
}
if ($right -gt 0 -and $left -gt 0) {
    [Console]::Error.WriteLine("needs_explicit_merge_decision: local main diverged from $Remote/$Branch; left=$left right=$right")
    exit 3
}

$candidateTip = Invoke-GitOne @("rev-parse", "--verify", $Candidate)
$before = Invoke-GitOne @("rev-parse", "--verify", "HEAD")
$checker = Join-Path $repoRoot "scripts\diagnostics\check-candidate-tip.ps1"
$json = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $checker -CurrentMain HEAD -CandidateTip $candidateTip
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("candidate_tip_check_failed")
    exit 1
}

$result = $json | ConvertFrom-Json
$blockers = @($result.blockers)
if ($blockers.Count -gt 0) {
    [Console]::Error.WriteLine("candidate_tip_guard_blocked: blockers=$($blockers -join ', ')")
    [Console]::Error.WriteLine($json)
    exit 1
}

git merge --ff-only $candidateTip | Out-Null
if ($LASTEXITCODE -ne 0) {
    [Console]::Error.WriteLine("rebuild_needed: candidate is not a fast-forward of current main; raw merge was not attempted")
    exit $LASTEXITCODE
}

$mergeCommits = @(git rev-list --merges "$before..HEAD" | Where-Object { $_.Trim() })
if ($mergeCommits.Count -gt 0) {
    [Console]::Error.WriteLine("repair_needed: fast-forward introduced merge commits; count=$($mergeCommits.Count)")
    exit 4
}

[pscustomobject]@{
    status = "push_ready"
    before = $before
    head = (Invoke-GitOne @("rev-parse", "--verify", "HEAD"))
    candidate = $candidateTip
    remote_left = $left
    remote_right = $right
    merge_commits = @()
} | ConvertTo-Json -Depth 4

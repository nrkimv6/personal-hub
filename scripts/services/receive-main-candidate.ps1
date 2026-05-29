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

function Get-TupleRelation {
    param([int]$Left, [int]$Right)
    if ($Left -eq 0 -and $Right -eq 0) { return "equal" }
    if ($Left -gt 0 -and $Right -eq 0) { return "ahead-only" }
    if ($Left -eq 0 -and $Right -gt 0) { return "behind-only" }
    if ($Left -gt 0 -and $Right -gt 0) { return "diverged" }
    return "unknown"
}

function Get-RevListTuple {
    param(
        [string]$RefSpec,
        [switch]$Optional
    )
    if ($Optional -and $RefSpec -match "\.\.\.(.+)$") {
        $rightRef = $Matches[1]
        $oldErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $null = & git rev-parse --verify $rightRef 2>&1
        $verifyExitCode = $LASTEXITCODE
        $ErrorActionPreference = $oldErrorActionPreference
        if ($verifyExitCode -ne 0) {
            return [pscustomobject]@{
                refspec = $RefSpec
                available = $false
                left = $null
                right = $null
                relation = "unavailable"
                error = "$rightRef unavailable"
            }
        }
    }
    $output = & git rev-list --left-right --count $RefSpec 2>&1
    if ($LASTEXITCODE -ne 0) {
        if ($Optional) {
            return [pscustomobject]@{
                refspec = $RefSpec
                available = $false
                left = $null
                right = $null
                relation = "unavailable"
                error = (($output -join "`n").Trim())
            }
        }
        throw "git rev-list --left-right --count $RefSpec failed: $($output -join "`n")"
    }
    $parts = (($output -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First 1).Trim() -split "\s+"
    $leftValue = [int]$parts[0]
    $rightValue = [int]$parts[1]
    return [pscustomobject]@{
        refspec = $RefSpec
        available = $true
        left = $leftValue
        right = $rightValue
        relation = Get-TupleRelation -Left $leftValue -Right $rightValue
        error = $null
    }
}

function Get-CloseoutStatus {
    param([pscustomobject]$Tuple)
    if (-not $Tuple.available) { return "remote_ref_unavailable" }
    if ($Tuple.left -eq 0 -and $Tuple.right -eq 0) { return "remote_aligned" }
    if ($Tuple.left -gt 0 -and $Tuple.right -eq 0) { return "push_required" }
    if ($Tuple.left -eq 0 -and $Tuple.right -gt 0) { return "remote_receive_required" }
    if ($Tuple.left -gt 0 -and $Tuple.right -gt 0) { return "remote_diverged" }
    return "remote_alignment_unknown"
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

$preReceiveFetchHead = Get-RevListTuple -RefSpec "HEAD...FETCH_HEAD"
$left = [int]$preReceiveFetchHead.left
$right = [int]$preReceiveFetchHead.right

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

$postReceiveFetchHead = Get-RevListTuple -RefSpec "HEAD...FETCH_HEAD"
$originMainTuple = Get-RevListTuple -RefSpec "HEAD...origin/main" -Optional
$decisionTuple = $originMainTuple
if (-not $decisionTuple.available) {
    $decisionTuple = $postReceiveFetchHead
}
$closeoutStatus = Get-CloseoutStatus -Tuple $decisionTuple
$pushRequired = $closeoutStatus -eq "push_required"
$remoteAligned = $closeoutStatus -eq "remote_aligned"

[pscustomobject]@{
    status = "push_ready"
    closeout_status = $closeoutStatus
    push_required = $pushRequired
    remote_aligned = $remoteAligned
    message = if ($pushRequired) { "push/read-back required before closeout" } else { "remote alignment read-back recorded" }
    before = $before
    head = (Invoke-GitOne @("rev-parse", "--verify", "HEAD"))
    candidate = $candidateTip
    remote_left = $decisionTuple.left
    remote_right = $decisionTuple.right
    remote_relation = $decisionTuple.relation
    pre_receive_fetch_head = $preReceiveFetchHead
    post_receive_fetch_head = $postReceiveFetchHead
    origin_main = $originMainTuple
    merge_commits = @()
} | ConvertTo-Json -Depth 4

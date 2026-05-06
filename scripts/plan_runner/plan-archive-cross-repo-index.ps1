param(
    [Parameter(Mandatory = $true)]
    [int]$RecordId,
    [int]$MaxCommits = 30,
    [switch]$Apply,
    [string]$BaseUrl = "http://127.0.0.1:6100"
)

$ErrorActionPreference = "Stop"

$body = @{
    record_id = $RecordId
    max_commits = $MaxCommits
    apply = [bool]$Apply
}

$json = $body | ConvertTo-Json -Depth 5
$uri = "$BaseUrl/api/v1/plans/retrieval/cross-repo/index"
Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json; charset=utf-8" -Body $json

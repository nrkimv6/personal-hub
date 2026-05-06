param(
    [int]$RecordId = 0,
    [int]$Limit = 50,
    [switch]$Force,
    [string]$Since = "",
    [switch]$Apply,
    [string]$BaseUrl = "http://127.0.0.1:6100"
)

$ErrorActionPreference = "Stop"

$body = @{
    limit = $Limit
    force = [bool]$Force
    apply = [bool]$Apply
}

if ($RecordId -gt 0) {
    $body.record_id = $RecordId
}
if ($Since.Trim()) {
    $body.since = $Since
}

$json = $body | ConvertTo-Json -Depth 5
$uri = "$BaseUrl/api/v1/plans/records/index"
Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json; charset=utf-8" -Body $json

param(
    [int]$Limit = 50,
    [switch]$Force,
    [switch]$DryRun,
    [string]$Provider = "",
    [string]$Model = "",
    [int]$Dimension = 0,
    [int]$TimeoutSeconds = 0,
    [string]$BaseUrl = "http://127.0.0.1:6100"
)

$ErrorActionPreference = "Stop"

$body = @{
    limit = $Limit
    force = [bool]$Force
    apply = -not [bool]$DryRun
}

if ($Provider.Trim()) {
    $body.provider = $Provider
}
if ($Model.Trim()) {
    $body.model = $Model
}
if ($Dimension -gt 0) {
    $body.dimension = $Dimension
}
if ($TimeoutSeconds -gt 0) {
    $body.timeout_seconds = $TimeoutSeconds
}

$json = $body | ConvertTo-Json -Depth 5
$uri = "$BaseUrl/api/v1/plans/retrieval/embeddings/index"
Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json; charset=utf-8" -Body $json

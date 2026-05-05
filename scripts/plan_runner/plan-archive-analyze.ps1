param(
    [Parameter(Mandatory=$true)]
    [int]$RecordId,

    [ValidateSet("preview", "apply")]
    [string]$Mode = "preview",

    [string]$Provider = "codex",
    [string]$Model = "gpt-5.2",
    [int]$TimeoutSeconds = 120,
    [switch]$IncludePrompt,
    [switch]$ConfirmApply,
    [string]$BaseUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"

if ($Mode -eq "apply" -and -not $ConfirmApply) {
    throw "Mode=apply requires -ConfirmApply."
}

$body = @{
    mode = $Mode
    provider = $Provider
    model = $Model
    timeout_seconds = $TimeoutSeconds
    include_prompt = [bool]$IncludePrompt
    source = "auto"
} | ConvertTo-Json -Depth 5

$uri = "$BaseUrl/api/v1/plans/records/$RecordId/analyze"
$response = Invoke-RestMethod -Method Post -Uri $uri -ContentType "application/json; charset=utf-8" -Body $body
$response | ConvertTo-Json -Depth 20

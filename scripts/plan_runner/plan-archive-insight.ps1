param(
    [string]$BaseUrl = "http://127.0.0.1:6100",
    [datetime]$DateFrom,
    [datetime]$DateTo,
    [string]$Grouping = "category",
    [string]$Category,
    [string]$Path,
    [int]$Limit = 20,
    [int]$TokenBudget = 3000,
    [string]$Provider,
    [string]$Model,
    [switch]$Apply,
    [switch]$Force
)

$body = @{
    grouping = $Grouping
    limit = $Limit
    token_budget = $TokenBudget
    apply = [bool]$Apply
    force = [bool]$Force
}
if ($PSBoundParameters.ContainsKey("DateFrom")) { $body.date_from = $DateFrom.ToString("o") }
if ($PSBoundParameters.ContainsKey("DateTo")) { $body.date_to = $DateTo.ToString("o") }
if ($Category) { $body.category = $Category }
if ($Path) { $body.path = $Path }
if ($Provider) { $body.provider = $Provider }
if ($Model) { $body.model = $Model }

$json = $body | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri "$BaseUrl/api/v1/plans/insights/batch" -Body $json -ContentType "application/json"

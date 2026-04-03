param(
    [string]$BaseUrl = "http://localhost:6101",
    [string]$AdminToken = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not $AdminToken -and $env:RECOVERY_ADMIN_TOKEN) {
    $AdminToken = $env:RECOVERY_ADMIN_TOKEN
}

function New-Headers {
    param(
        [switch]$Json,
        [switch]$WithToken
    )
    $headers = @{}
    if ($Json) { $headers["Content-Type"] = "application/json" }
    if ($WithToken -and $AdminToken) { $headers["x-recovery-admin-token"] = $AdminToken }
    return $headers
}

function Get-StatusCode {
    param([System.Exception]$Exception)
    if ($Exception.Response -and $Exception.Response.StatusCode) {
        return [int]$Exception.Response.StatusCode
    }
    return -1
}

Write-Host "[1/3] GET /recovery/process-watch" -ForegroundColor Cyan
$watchUri = "$BaseUrl/recovery/process-watch?min_mb=0&limit=10"
try {
    $watch = Invoke-RestMethod -Method Get -Uri $watchUri -Headers (New-Headers -WithToken)
    if (-not $watch.items) {
        throw "process-watch 응답에 items가 없습니다."
    }
    Write-Host ("  OK: item_count={0}, source={1}, transport={2}" -f $watch.item_count, $watch.source, $watch.transport) -ForegroundColor Green
} catch {
    $statusCode = Get-StatusCode -Exception $_.Exception
    if ($statusCode -eq 403 -and -not $AdminToken) {
        throw "관리자 토큰이 없어 403이 반환되었습니다. -AdminToken 또는 RECOVERY_ADMIN_TOKEN을 설정하세요."
    }
    throw
}

Write-Host "[2/3] POST /recovery/process-kill (unauthorized must be 403)" -ForegroundColor Cyan
$unauthCode = -1
try {
    $payload = @{ pid = 1; reason = "unauthorized smoke"; force = $true } | ConvertTo-Json -Depth 5
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/recovery/process-kill" -Headers (New-Headers -Json) -Body $payload | Out-Null
    throw "unauthorized 요청이 차단되지 않았습니다."
} catch {
    $unauthCode = Get-StatusCode -Exception $_.Exception
}
if ($unauthCode -ne 403) {
    throw "unauthorized 차단 검증 실패: expected=403 actual=$unauthCode"
}
Write-Host "  OK: unauthorized 403" -ForegroundColor Green

Write-Host "[3/3] POST /recovery/process-kill (fingerprint mismatch must be 409)" -ForegroundColor Cyan
$target = $watch.items | Select-Object -First 1
if (-not $target) {
    throw "fingerprint mismatch 검증용 대상 프로세스가 없습니다."
}

$mismatchCode = -1
try {
    $mismatchPayload = @{
        pid = [int]$target.pid
        expected_create_time = $target.create_time
        expected_cmdline_hash = "ffffffffffffffffffffffffffffffff"
        reason = "smoke fingerprint mismatch"
        force = ($target.scope -ne "monitor_page")
    } | ConvertTo-Json -Depth 6

    Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/recovery/process-kill" `
        -Headers (New-Headers -Json -WithToken) `
        -Body $mismatchPayload | Out-Null

    throw "fingerprint mismatch 요청이 차단되지 않았습니다."
} catch {
    $mismatchCode = Get-StatusCode -Exception $_.Exception
}

if ($mismatchCode -ne 409) {
    throw "fingerprint mismatch 검증 실패: expected=409 actual=$mismatchCode"
}
Write-Host "  OK: fingerprint mismatch 409" -ForegroundColor Green

Write-Host "Recovery process-watch smoke passed." -ForegroundColor Green

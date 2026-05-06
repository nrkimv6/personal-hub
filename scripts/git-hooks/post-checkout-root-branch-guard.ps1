param(
    [string]$PreviousHead = "",
    [string]$NewHead = "",
    [string]$IsBranchCheckout = ""
)

$ErrorActionPreference = "Stop"

$guard = Join-Path $PSScriptRoot "root-branch-guard.ps1"
if (-not (Test-Path -LiteralPath $guard)) {
    exit 0
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $guard -Mode PostCheckout
$code = $LASTEXITCODE
if ($code -ne 0) {
    Write-Error "post-checkout root branch guard failed (previous=$PreviousHead, new=$NewHead, branch_checkout=$IsBranchCheckout)"
    exit $code
}

exit 0

param(
    [switch]$KeepStateFile
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
$StateFile = Join-Path $ProjectRoot "logs\kakao_guard_state.json"

Add-Type -Namespace Win32 -Name UserInput -MemberDefinition @"
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern bool BlockInput(bool fBlockIt);
"@

$released = [Win32.UserInput]::BlockInput($false)
if (-not $released) {
    Write-Warning "BlockInput(false) returned false. Try from the same interactive session or elevated shell."
}

if ((Test-Path $StateFile) -and -not $KeepStateFile) {
    Remove-Item -LiteralPath $StateFile -Force
    Write-Host "Removed Kakao guard state file: $StateFile"
} elseif (Test-Path $StateFile) {
    Write-Host "Kept Kakao guard state file: $StateFile"
}

if ($released) {
    Write-Host "Kakao input guard release requested successfully."
}

# Monitor Page - Git Commit Script
# Usage: .\scripts\commit.ps1 "커밋 메시지"

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Message
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)

# Change to project root
Set-Location $ProjectRoot

# Check if there are changes to commit
$status = git status --porcelain
if (-not $status) {
    Write-Host "[!] No changes to commit" -ForegroundColor Yellow
    exit 0
}

# Show current status
Write-Host "`n[*] Current changes:" -ForegroundColor Cyan
git status --short

# Stage all changes
Write-Host "`n[*] Staging all changes..." -ForegroundColor Cyan
git add -A

# Commit with message
Write-Host "`n[*] Committing..." -ForegroundColor Cyan
git commit -m $Message

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[+] Commit successful!" -ForegroundColor Green

    # Show commit info
    Write-Host "`n[*] Commit info:" -ForegroundColor Cyan
    git log -1 --oneline
} else {
    Write-Host "`n[-] Commit failed!" -ForegroundColor Red
    exit 1
}

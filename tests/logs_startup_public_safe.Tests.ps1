#Requires -Version 5.1

BeforeAll {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
    $StartupScript = Join-Path $RepoRoot "scripts\logs\startup-logs.ps1"
    $LogsScript = Join-Path $RepoRoot "scripts\logs\logs.ps1"
    $StartupText = Get-Content -LiteralPath $StartupScript -Raw -Encoding UTF8
    $LogsText = Get-Content -LiteralPath $LogsScript -Raw -Encoding UTF8
}

Describe "Startup public-safe log viewer contract" {
    It "Public Logs command uses -PublicSafe" {
        $StartupText | Should -Match '\$publicSafeLogsCmd'
        $StartupText | Should -Match "-Follow\s+-PublicSafe"
        $StartupText | Should -Match 'Public Safe Logs'
    }

    It "logs.ps1 defines PublicSafe and forwards --public-safe" {
        $LogsText | Should -Match '\[switch\]\$PublicSafe'
        $LogsText | Should -Match "--public-safe"
    }

    It "Admin and Watchdog commands keep -Admin" {
        $StartupText | Should -Match '\$adminLogsCmd'
        $StartupText | Should -Match '\$watchdogLogsCmd'
        $StartupText | Should -Match "-Follow\s+-Admin"
        $StartupText | Should -Match "-Follow\s+-Admin\s+watchdog"
    }

    It "PowerShell scripts have no parse errors" {
        foreach ($script in @($StartupScript, $LogsScript)) {
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $script, [ref]$null, [ref]$errors
            ) | Out-Null
            $errors.Count | Should -Be 0
        }
    }
}

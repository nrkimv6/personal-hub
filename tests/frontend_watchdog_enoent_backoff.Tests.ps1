#Requires -Version 5.1

BeforeAll {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
    . (Join-Path $RepoRoot "scripts\watchdogs\frontend-watchdog-lib.ps1")
}

Describe "frontend watchdog SvelteKit ENOENT backoff" {
    BeforeEach {
        $script:TempLogDir = Join-Path ([System.IO.Path]::GetTempPath()) ("monitor-watchdog-enoent-" + [System.Guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $script:TempLogDir -Force | Out-Null
    }

    AfterEach {
        Remove-Item -LiteralPath $script:TempLogDir -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item Env:\FRONTEND_WATCHDOG_ENOENT_PAUSE_MINUTES -ErrorAction SilentlyContinue
    }

    It "Test-FrontendEnoentCrashLog returns true for SvelteKit createProxy ENOENT logs" {
        $log = Join-Path $script:TempLogDir "frontend_err_20260515.log"
        @"
Error: ENOENT: no such file or directory, open 'src/routes/new/+page.ts'
    at createProxy (node_modules/@sveltejs/kit/src/core/sync/write_types/index.js:538:19)
"@ | Set-Content -LiteralPath $log -Encoding UTF8

        Test-FrontendEnoentCrashLog -LogPath $log | Should -BeTrue
    }

    It "Test-FrontendEnoentCrashLog returns false for general crash logs" {
        $log = Join-Path $script:TempLogDir "frontend_err_20260515.log"
        "TypeError: Cannot read properties of undefined" | Set-Content -LiteralPath $log -Encoding UTF8

        Test-FrontendEnoentCrashLog -LogPath $log | Should -BeFalse
    }

    It "Test-ShouldShortBackoff returns false when no frontend stderr log exists" {
        Test-ShouldShortBackoff -LogDir $script:TempLogDir | Should -BeFalse
    }

    It "selects latest stderr log, detects ENOENT, and calculates a 10 minute pause" {
        $old = Join-Path $script:TempLogDir "frontend_err_old.log"
        $latest = Join-Path $script:TempLogDir "frontend_err_latest.log"
        "TypeError: unrelated" | Set-Content -LiteralPath $old -Encoding UTF8
        Start-Sleep -Milliseconds 20
        @"
Error: ENOENT: no such file or directory, open 'src/routes/new/+page.ts'
    at createProxy (node_modules/@sveltejs/kit/src/core/sync/write_types/index.js:538:19)
"@ | Set-Content -LiteralPath $latest -Encoding UTF8

        Test-ShouldShortBackoff -LogDir $script:TempLogDir | Should -BeTrue
        Get-FrontendBackoffPauseMinutes -StandardPauseMinutes 60 | Should -Be 10
    }
}

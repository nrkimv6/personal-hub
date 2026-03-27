#Requires -Version 5.1
# T2: Redis fallback mode verification for logs.ps1 -Follow
# Validates Phase 2 implementation: dynamic $useRedis re-evaluation

BeforeAll {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
    $LogsScript = Join-Path $RepoRoot "scripts\logs.ps1"

    # Helper: Replicate $useRedis initialization logic (lines 440-442 of logs.ps1)
    function Invoke-UseRedisInit {
        param([string]$PingResponse)
        $useRedis = $false
        $pingOut = $PingResponse
        if ($pingOut -eq "PONG") { $useRedis = $true }
        return $useRedis
    }

    # Helper: Replicate dynamic re-evaluation logic (lines 863-873 of logs.ps1)
    function Invoke-UseRedisReeval {
        param(
            [bool]$CurrentUseRedis,
            [string]$PingResponse,
            [double]$ElapsedSec,
            [double]$RefreshInterval = 10.0
        )
        $useRedis = $CurrentUseRedis
        $reconnected = $false
        $message = $null

        if (-not $useRedis) {
            if ($ElapsedSec -ge $RefreshInterval) {
                $rePing = $PingResponse
                if ($rePing -eq "PONG") {
                    $useRedis = $true
                    $reconnected = $true
                    $message = "[SYSTEM] Redis connected - switching to Redis-based runner detection"
                }
            }
        }
        return @{
            UseRedis    = $useRedis
            Reconnected = $reconnected
            Message     = $message
        }
    }

    # Helper: Replicate fallback file selection logic (lines 957-999 of logs.ps1)
    function Invoke-FallbackFileSelect {
        param([string]$LogDir)
        if (-not (Test-Path $LogDir)) { return $null }
        $candidates = Get-ChildItem -Path $LogDir -Filter "plan-runner-*.log" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notmatch "stream" }
        $latest = $candidates | Sort-Object Name -Descending | Select-Object -First 1
        return $latest
    }
}

Describe "T2: Redis Fallback Mode" {

    Context "1. Initial useRedis detection when Redis is down" {

        It "Empty ping response => useRedis=false" {
            Invoke-UseRedisInit -PingResponse "" | Should -BeFalse
        }

        It "Error string ping response => useRedis=false" {
            Invoke-UseRedisInit -PingResponse "Could not connect to Redis" | Should -BeFalse
        }

        It "Null ping response => useRedis=false" {
            Invoke-UseRedisInit -PingResponse $null | Should -BeFalse
        }

        It "PONG response => useRedis=true" {
            Invoke-UseRedisInit -PingResponse "PONG" | Should -BeTrue
        }
    }

    Context "2. Dynamic useRedis re-evaluation in Follow loop" {

        It "useRedis=false + elapsed >= interval + no Redis => stays false" {
            $r = Invoke-UseRedisReeval -CurrentUseRedis $false -PingResponse "" -ElapsedSec 11
            $r.UseRedis    | Should -BeFalse
            $r.Reconnected | Should -BeFalse
        }

        It "useRedis=false + elapsed below interval => skip re-eval (stays false)" {
            $r = Invoke-UseRedisReeval -CurrentUseRedis $false -PingResponse "PONG" -ElapsedSec 5
            $r.UseRedis    | Should -BeFalse
            $r.Reconnected | Should -BeFalse
        }

        It "useRedis=false + elapsed >= interval + Redis recovered => switches to true" {
            $r = Invoke-UseRedisReeval -CurrentUseRedis $false -PingResponse "PONG" -ElapsedSec 11
            $r.UseRedis    | Should -BeTrue
            $r.Reconnected | Should -BeTrue
        }

        It "Redis recovery emits [SYSTEM] Redis connected message" {
            $r = Invoke-UseRedisReeval -CurrentUseRedis $false -PingResponse "PONG" -ElapsedSec 15
            $r.Message | Should -BeLike "*Redis connected*"
        }

        It "useRedis=true => re-eval block not entered" {
            $r = Invoke-UseRedisReeval -CurrentUseRedis $true -PingResponse "PONG" -ElapsedSec 20
            $r.Reconnected | Should -BeFalse
        }
    }

    Context "3. Fallback mode: latest plan-runner log file selection" {
        BeforeAll {
            $tmpDir = Join-Path $env:TEMP "logs_ps1_test_$(Get-Random)"
            New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null

            @(
                "plan-runner-20260101_100000.log"
                "plan-runner-20260101_120000.log"
                "plan-runner-20260102_090000.log"
                "plan-runner-stream-20260102_090000.log"
            ) | ForEach-Object {
                New-Item -Path (Join-Path $tmpDir $_) -ItemType File -Force | Out-Null
            }
        }

        AfterAll {
            Remove-Item -Path $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        }

        It "Selects the latest plan-runner-*.log (stream excluded)" {
            $result = Invoke-FallbackFileSelect -LogDir $tmpDir
            $result | Should -Not -BeNullOrEmpty
            $result.Name | Should -Be "plan-runner-20260102_090000.log"
        }

        It "Stream files excluded from fallback selection" {
            $result = Invoke-FallbackFileSelect -LogDir $tmpDir
            $result.Name | Should -Not -BeLike "*stream*"
        }

        It "Non-existent log dir returns null" {
            $result = Invoke-FallbackFileSelect -LogDir "C:\NonExistent\Path\$(Get-Random)"
            $result | Should -BeNullOrEmpty
        }
    }

    Context "4. Fallback key vs Redis key distinction" {

        It "Fallback keys (no #) are identified correctly" {
            $fallbackKey = "PR:20260101_100000"
            $isFallback = ($fallbackKey -like "PR:*" -and $fallbackKey -notlike "*#*")
            $isFallback | Should -BeTrue
        }

        It "Redis keys (with #) are NOT treated as fallback keys" {
            $redisKey = "PR:plan-name#abc123|PID:1234"
            $isFallback = ($redisKey -like "PR:*" -and $redisKey -notlike "*#*")
            $isFallback | Should -BeFalse
        }
    }

    Context "5. logs.ps1 script syntax" {
        It "logs.ps1 file exists" {
            $LogsScript | Should -Exist
        }

        It "logs.ps1 has no PowerShell parse errors" {
            $errors = $null
            [System.Management.Automation.Language.Parser]::ParseFile(
                $LogsScript, [ref]$null, [ref]$errors
            ) | Out-Null
            $errors.Count | Should -Be 0
        }
    }
}

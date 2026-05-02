#Requires -Version 5.1
# T2: Redis fallback mode verification for logs.ps1 -Follow
# Validates Phase 2 implementation: dynamic $useRedis re-evaluation

BeforeAll {
    $RepoRoot = Split-Path $PSScriptRoot -Parent
    $LogsScript = Join-Path $RepoRoot "scripts\logs\logs.ps1"

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

    # Helper: Replicate stream matching logic (runner/file id 우선, 글로벌 최신 stream 폴백 금지)
    function Invoke-MatchStreamFile {
        param(
            [string]$LogDir,
            [string]$PlanLogFileName,
            [string]$RunnerId = ""
        )
        if (-not (Test-Path $LogDir) -or -not $PlanLogFileName) { return $null }

        if ($RunnerId) {
            $byRunner = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${RunnerId}*.log" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($byRunner) { return $byRunner }
        }

        if ($PlanLogFileName -match 'plan-runner-(t-.+)-\d{8}-\d{6}') {
            $fileId = $Matches[1]
            $byFileId = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${fileId}*.log" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($byFileId) { return $byFileId }
        }
        if ($PlanLogFileName -match 'plan-runner-([0-9a-f]{8})-\d{8}-\d{6}') {
            $fileId = $Matches[1]
            $byFileId = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${fileId}*.log" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($byFileId) { return $byFileId }
        }
        if ($PlanLogFileName -match 'plan-runner-(?:t-.+|[0-9a-f]{8})-(\d{8}-\d{6})') {
            $stamp = $Matches[1]
            $byStamp = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${stamp}*.log" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($byStamp) { return $byStamp }
        }
        if ($PlanLogFileName -match 'plan-runner-(\d{8}-\d{6})') {
            $stamp = $Matches[1]
            $byStamp = Get-ChildItem -Path $LogDir -Filter "plan-runner-stream-*${stamp}*.log" -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($byStamp) { return $byStamp }
        }

        return $null
    }

    function Invoke-StreamMissWarning {
        param(
            [hashtable]$Seen,
            [string]$Key,
            [string]$PlanLogFileName,
            [string]$RunnerId = ""
        )
        if (-not $Key) { $Key = "PS:unknown" }
        if ($Seen.ContainsKey($Key)) { return $null }
        $Seen[$Key] = $true
        $runnerHint = if ($RunnerId) { " runner=$RunnerId" } else { "" }
        $fileHint = if ($PlanLogFileName) { " planLog=$PlanLogFileName" } else { "" }
        return "[$Key] [WARN] matching plan-runner stream log not found.$runnerHint$fileHint"
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

    Context "5. Stream file matching safety" {
        BeforeAll {
            $tmpDir2 = Join-Path $env:TEMP "logs_ps1_stream_test_$(Get-Random)"
            New-Item -ItemType Directory -Path $tmpDir2 -Force | Out-Null
            @(
                "plan-runner-7bdb249d-20260403-001108.log",
                "plan-runner-stream-f6e1dc20-20260402_162850.log",
                "plan-runner-stream-7bdb249d-20260403_001108.log"
            ) | ForEach-Object {
                New-Item -Path (Join-Path $tmpDir2 $_) -ItemType File -Force | Out-Null
            }
        }

        AfterAll {
            Remove-Item -Path $tmpDir2 -Recurse -Force -ErrorAction SilentlyContinue
        }

        It "Matches stream by runner id when available" {
            $result = Invoke-MatchStreamFile -LogDir $tmpDir2 -PlanLogFileName "plan-runner-7bdb249d-20260403-001108.log" -RunnerId "7bdb249d"
            $result | Should -Not -BeNullOrEmpty
            $result.Name | Should -Be "plan-runner-stream-7bdb249d-20260403_001108.log"
        }

        It "Returns null when no matching stream exists (no global latest fallback)" {
            Remove-Item -Path (Join-Path $tmpDir2 "plan-runner-stream-7bdb249d-20260403_001108.log") -Force
            $result = Invoke-MatchStreamFile -LogDir $tmpDir2 -PlanLogFileName "plan-runner-7bdb249d-20260403-001108.log" -RunnerId "7bdb249d"
            $result | Should -BeNullOrEmpty
        }

        It "Returns null for non-standard plan-runner names without selecting global latest stream" {
            $result = Invoke-MatchStreamFile -LogDir $tmpDir2 -PlanLogFileName "plan-runner-x-token.log" -RunnerId ""
            $result | Should -BeNullOrEmpty
        }
    }

    Context "6. Stream mismatch diagnostics" {
        It "Emits one warning per PS key when stream matching fails" {
            $seen = @{}
            $first = Invoke-StreamMissWarning -Seen $seen -Key "PS:plan#7bdb" -PlanLogFileName "plan-runner-x-token.log" -RunnerId "7bdb249d"
            $second = Invoke-StreamMissWarning -Seen $seen -Key "PS:plan#7bdb" -PlanLogFileName "plan-runner-x-token.log" -RunnerId "7bdb249d"

            $first | Should -BeLike "*matching plan-runner stream log not found*"
            $first | Should -BeLike "*runner=7bdb249d*"
            $second | Should -BeNullOrEmpty
        }
    }

    Context "7. logs.ps1 script syntax" {
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

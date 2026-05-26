param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot,

    [Parameter(Mandatory = $true)]
    [string]$Operation,

    [int]$TimeoutSeconds = 300,

    [int]$PollMilliseconds = 200,

    [ValidateSet("Auto", "File", "Redis")]
    [string]$Backend = "Auto",

    [Parameter(Mandatory = $true)]
    [scriptblock]$ScriptBlock
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Fail-WithCode {
    param(
        [string]$Message,
        [int]$Code = 1
    )

    [Console]::Error.WriteLine($Message)
    [Environment]::Exit($Code)
}

function Resolve-RepoRoot {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Fail-WithCode "RepoRoot does not exist: $Path" 1
    }

    $resolved = (Resolve-Path -LiteralPath $Path).ProviderPath
    & git -C $resolved rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail-WithCode "RepoRoot is not a git worktree: $resolved" 1
    }

    return [System.IO.Path]::GetFullPath($resolved).TrimEnd('\', '/')
}

function Invoke-GitSingleLine {
    param(
        [string]$Root,
        [string[]]$GitArgs,
        [string]$Fallback
    )

    $lines = @(& git -C $Root @GitArgs 2>$null)
    if ($LASTEXITCODE -eq 0 -and $lines.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace([string]$lines[0])) {
        return ([string]$lines[0]).Trim()
    }
    return $Fallback
}

function Resolve-LockPath {
    param([string]$Root)

    $fallback = Join-Path $Root ".git\plan-docs-queue.lock"
    $path = Invoke-GitSingleLine -Root $Root -GitArgs @("rev-parse", "--git-path", "plan-docs-queue.lock") -Fallback $fallback
    if ([System.IO.Path]::IsPathRooted($path)) {
        return [System.IO.Path]::GetFullPath($path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $Root $path))
}

function Write-LockMetadata {
    param(
        [System.IO.FileStream]$Stream,
        [string]$Root,
        [string]$GitDir,
        [string]$Op
    )

    $processName = ""
    try {
        $processName = (Get-Process -Id $PID).ProcessName
    } catch {
        $processName = "unknown"
    }

    $metadata = [ordered]@{
        pid = $PID
        processName = $processName
        repoRoot = $Root
        gitDir = $GitDir
        startedAt = [DateTime]::UtcNow.ToString("o")
        operation = $Op
        surface = "plan-docs"
    }
    $json = ($metadata | ConvertTo-Json -Depth 5)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $Stream.SetLength(0)
    $Stream.Position = 0
    $Stream.Write($bytes, 0, $bytes.Length)
    $Stream.Flush()
}

function Read-LockOwnerText {
    param([string]$Path)

    try {
        if (Test-Path -LiteralPath $Path -PathType Leaf) {
            return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8)
        }
    } catch {
        return "unreadable owner metadata: $($_.Exception.Message)"
    }
    return "owner metadata unavailable"
}

function Format-TimeoutMessage {
    param(
        [string]$OwnerText,
        [double]$ElapsedSeconds
    )

    try {
        $owner = $OwnerText | ConvertFrom-Json
        return ("PLAN_DOCS_LOCK_TIMEOUT: owner_pid={0} operation={1} started={2} elapsed={3}s" -f $owner.pid, $owner.operation, $owner.startedAt, [Math]::Round($ElapsedSeconds, 1))
    } catch {
        return ("PLAN_DOCS_LOCK_TIMEOUT: owner={0} elapsed={1}s" -f ($OwnerText -replace '\s+', ' ').Trim(), [Math]::Round($ElapsedSeconds, 1))
    }
}

function Invoke-WithFileLock {
    param(
        [string]$Root,
        [string]$LockPath,
        [scriptblock]$Body
    )

    $parent = Split-Path -Parent $LockPath
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $started = [DateTime]::UtcNow
    $deadline = $started.AddSeconds($TimeoutSeconds)
    $gitDir = Invoke-GitSingleLine -Root $Root -GitArgs @("rev-parse", "--git-dir") -Fallback ""
    $stream = $null

    while ([DateTime]::UtcNow -le $deadline) {
        try {
            $stream = [System.IO.FileStream]::new($LockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            Write-LockMetadata -Stream $stream -Root $Root -GitDir $gitDir -Op $Operation
            $oldHeldRepo = $env:PLAN_DOCS_LOCK_HELD_REPO
            $oldHeldPath = $env:PLAN_DOCS_LOCK_HELD_PATH
            try {
                $env:PLAN_DOCS_LOCK_HELD_REPO = $Root
                $env:PLAN_DOCS_LOCK_HELD_PATH = $LockPath
                & $Body
            } finally {
                $env:PLAN_DOCS_LOCK_HELD_REPO = $oldHeldRepo
                $env:PLAN_DOCS_LOCK_HELD_PATH = $oldHeldPath
                $stream.Dispose()
            }
            return
        } catch [System.IO.IOException] {
            if ($stream) {
                $stream.Dispose()
                $stream = $null
            }
            if ([DateTime]::UtcNow -gt $deadline) {
                break
            }
            Start-Sleep -Milliseconds $PollMilliseconds
        }
    }

    $ownerText = Read-LockOwnerText -Path $LockPath
    $elapsed = ([DateTime]::UtcNow - $started).TotalSeconds
    Fail-WithCode (Format-TimeoutMessage -OwnerText $ownerText -ElapsedSeconds $elapsed) 7
}

function Get-RedisCli {
    $command = Get-Command redis-cli -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return ""
}

function Get-RedisKey {
    param([string]$Root)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Root.ToLowerInvariant())
        $hashBytes = $sha.ComputeHash($bytes)
        $hash = -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
        return "plan-docs-lock:$hash"
    } finally {
        $sha.Dispose()
    }
}

function Invoke-RedisCli {
    param(
        [string]$RedisCli,
        [string]$RedisUrl,
        [string[]]$Args
    )

    return @(& $RedisCli -u $RedisUrl @Args 2>&1)
}

function Invoke-WithRedisLock {
    param(
        [string]$Root,
        [scriptblock]$Body
    )

    $redisUrl = $env:PLAN_DOCS_LOCK_REDIS_URL
    if ([string]::IsNullOrWhiteSpace($redisUrl)) {
        Fail-WithCode "PLAN_DOCS_LOCK_REDIS_UNAVAILABLE: PLAN_DOCS_LOCK_REDIS_URL is not set" 8
    }

    $redisCli = Get-RedisCli
    if (-not $redisCli) {
        Fail-WithCode "PLAN_DOCS_LOCK_REDIS_UNAVAILABLE: redis-cli not found" 8
    }

    $key = Get-RedisKey -Root $Root
    $token = "$PID-$([Guid]::NewGuid().ToString('N'))"
    $ttl = [Math]::Max($TimeoutSeconds + 30, 30)
    $started = [DateTime]::UtcNow
    $deadline = $started.AddSeconds($TimeoutSeconds)
    $acquired = $false

    while ([DateTime]::UtcNow -le $deadline) {
        $result = Invoke-RedisCli -RedisCli $redisCli -RedisUrl $redisUrl -Args @("--raw", "SET", $key, $token, "NX", "EX", ([string]$ttl))
        if ($LASTEXITCODE -ne 0) {
            Fail-WithCode "PLAN_DOCS_LOCK_REDIS_UNAVAILABLE: $($result -join ' ')" 8
        }
        if (($result -join "").Trim() -eq "OK") {
            $acquired = $true
            break
        }
        Start-Sleep -Milliseconds $PollMilliseconds
    }

    if (-not $acquired) {
        $elapsed = ([DateTime]::UtcNow - $started).TotalSeconds
        Fail-WithCode ("PLAN_DOCS_LOCK_TIMEOUT: owner_pid=redis operation=unknown started=unknown elapsed={0}s" -f [Math]::Round($elapsed, 1)) 7
    }

    try {
        & $Body
    } finally {
        $releaseScript = 'if redis.call("get",KEYS[1])==ARGV[1] then return redis.call("del",KEYS[1]) else return 0 end'
        Invoke-RedisCli -RedisCli $redisCli -RedisUrl $redisUrl -Args @("--raw", "EVAL", $releaseScript, "1", $key, $token) | Out-Null
    }
}

function Resolve-BackendMode {
    if ($Backend -eq "File") {
        return "File"
    }
    if ($Backend -eq "Redis") {
        return "Redis"
    }

    $envBackend = $env:PLAN_DOCS_LOCK_BACKEND
    if (-not [string]::IsNullOrWhiteSpace($envBackend)) {
        if ($envBackend -notin @("Auto", "File", "Redis")) {
            Fail-WithCode "Invalid PLAN_DOCS_LOCK_BACKEND: $envBackend" 1
        }
        if ($envBackend -eq "Redis") {
            return "Redis"
        }
        if ($envBackend -eq "File") {
            return "File"
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($env:PLAN_DOCS_LOCK_REDIS_URL)) {
        return "Redis"
    }
    return "File"
}

function Resolve-EffectiveTimeoutSeconds {
    param(
        [int]$RequestedTimeoutSeconds,
        [bool]$WasExplicit
    )

    if ($WasExplicit) {
        return [Math]::Min($RequestedTimeoutSeconds, 3600)
    }

    if (-not [string]::IsNullOrWhiteSpace($env:PLAN_DOCS_LOCK_TIMEOUT)) {
        $parsedTimeout = 0
        if (-not [int]::TryParse($env:PLAN_DOCS_LOCK_TIMEOUT, [ref]$parsedTimeout)) {
            Fail-WithCode "Invalid PLAN_DOCS_LOCK_TIMEOUT: $env:PLAN_DOCS_LOCK_TIMEOUT" 1
        }
        return [Math]::Min([Math]::Max($parsedTimeout, 0), 3600)
    }

    if (-not [string]::IsNullOrWhiteSpace($env:PLAN_DOCS_LOCK_QUEUE_DEPTH)) {
        $queueDepth = 0
        if (-not [int]::TryParse($env:PLAN_DOCS_LOCK_QUEUE_DEPTH, [ref]$queueDepth)) {
            Fail-WithCode "Invalid PLAN_DOCS_LOCK_QUEUE_DEPTH: $env:PLAN_DOCS_LOCK_QUEUE_DEPTH" 1
        }
        if ($queueDepth -gt 0) {
            return [Math]::Max(60, [Math]::Min($queueDepth * 60, 3600))
        }
    }

    return [Math]::Min([Math]::Max($RequestedTimeoutSeconds, 0), 3600)
}

if ($TimeoutSeconds -lt 0) {
    Fail-WithCode "TimeoutSeconds must be >= 0" 1
}
if ($PollMilliseconds -lt 1) {
    Fail-WithCode "PollMilliseconds must be >= 1" 1
}

$TimeoutSeconds = Resolve-EffectiveTimeoutSeconds -RequestedTimeoutSeconds $TimeoutSeconds -WasExplicit $PSBoundParameters.ContainsKey("TimeoutSeconds")
$repo = Resolve-RepoRoot -Path $RepoRoot
$lockPath = Resolve-LockPath -Root $repo
$backendMode = Resolve-BackendMode

if ($backendMode -eq "Redis") {
    Invoke-WithRedisLock -Root $repo -Body {
        Invoke-WithFileLock -Root $repo -LockPath $lockPath -Body $ScriptBlock
    }
} else {
    Invoke-WithFileLock -Root $repo -LockPath $lockPath -Body $ScriptBlock
}

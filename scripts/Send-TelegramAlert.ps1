# Send-TelegramAlert.ps1
# PowerShell function to send Telegram alerts
# Used by api-watchdog.ps1 and other monitoring scripts
#
# Usage:
#   . .\scripts\Send-TelegramAlert.ps1  # Dot-source to load function
#   Send-TelegramAlert "Your message here"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptRoot

# Telegram configuration
# Read from config.py or use defaults
function Get-TelegramConfig {
    $configPath = Join-Path $ProjectRoot "app\core\config.py"

    $token = $null
    $chatId = $null

    if (Test-Path $configPath) {
        $content = Get-Content $configPath -Raw

        # Extract TELEGRAM_BOT_TOKEN
        if ($content -match 'TELEGRAM_BOT_TOKEN:\s*str\s*=\s*"([^"]+)"') {
            $token = $Matches[1]
        }

        # Extract TELEGRAM_CHAT_ID
        if ($content -match 'TELEGRAM_CHAT_ID:\s*str\s*=\s*"([^"]+)"') {
            $chatId = $Matches[1]
        }
    }

    # Also check .env for overrides
    $envPath = Join-Path $ProjectRoot ".env"
    if (Test-Path $envPath) {
        Get-Content $envPath | ForEach-Object {
            if ($_ -match '^TELEGRAM_BOT_TOKEN=(.+)$') {
                $token = $Matches[1].Trim('"', "'")
            }
            if ($_ -match '^TELEGRAM_CHAT_ID=(.+)$') {
                $chatId = $Matches[1].Trim('"', "'")
            }
        }
    }

    return @{
        Token = $token
        ChatId = $chatId
    }
}

function Send-TelegramAlert {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Message,

        [string]$ParseMode = "HTML"
    )

    $config = Get-TelegramConfig

    if (-not $config.Token -or -not $config.ChatId) {
        Write-Warning "Telegram configuration not found. Skipping alert."
        return $false
    }

    $url = "https://api.telegram.org/bot$($config.Token)/sendMessage"

    $body = @{
        chat_id = $config.ChatId
        text = $Message
        parse_mode = $ParseMode
    } | ConvertTo-Json -Compress

    try {
        $response = Invoke-RestMethod -Uri $url -Method POST -Body $body -ContentType "application/json; charset=utf-8"
        if ($response.ok) {
            Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Telegram alert sent successfully" -ForegroundColor Green
            return $true
        } else {
            Write-Warning "Telegram API returned error: $($response | ConvertTo-Json)"
            return $false
        }
    } catch {
        Write-Warning "Failed to send Telegram alert: $_"
        return $false
    }
}


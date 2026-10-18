[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Api', 'Web')]
    [string]$Service,

    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8008,

    [ValidateRange(1, 65535)]
    [int]$WebPort = 5181
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot '.env'
$python = Join-Path $repoRoot 'api/.venv/Scripts/python.exe'
$vite = Join-Path $repoRoot 'web/node_modules/vite/bin/vite.js'
$port = if ($Service -eq 'Api') { $ApiPort } else { $WebPort }

if ($ApiPort -eq $WebPort) {
    throw 'API and web ports must be different.'
}
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Create $envFile from .env.example and configure the API key before starting."
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Prepared API dependencies are missing: api/.venv/Scripts/python.exe. Install the API environment first.'
}

if ($Service -eq 'Web') {
    $node = Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1
    if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
        throw 'Prepared web dependencies are missing: web/node_modules/vite/bin/vite.js. Install the web dependencies first.'
    }
}

# Share the port-owner lookup and forced restart behavior with sysup.cmd.
# Dependencies are checked before stopping the current listener.
& $python (Join-Path $PSScriptRoot 'start_services.py') --release-port $port
if ($LASTEXITCODE -ne 0) {
    throw "Could not release port $port. See the launcher message above."
}

# Process environment takes precedence over dotenv, including a previously used
# demo setting. Restore it when this foreground launcher exits.
$liveEnvironment = @{
    DEMO_OFFLINE = '0'
    VITE_MOCK_API = '0'
    TP_SEED_FIXTURE_DESIGNS = '0'
    API_TARGET = "http://127.0.0.1:$ApiPort"
    WEB_PORT = "$WebPort"
}
$previousEnvironment = @{}
foreach ($name in $liveEnvironment.Keys) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

Push-Location -LiteralPath $repoRoot
try {
    foreach ($name in $liveEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $liveEnvironment[$name], 'Process')
    }

    Write-Host "Starting $Service in live mode at http://127.0.0.1:$port (Ctrl+C to stop this service)."
    if ($Service -eq 'Api') {
        & $python -m uvicorn trialpilot_api.main:create_app --factory --env-file $envFile --host 127.0.0.1 --port $ApiPort
    } else {
        Push-Location -LiteralPath (Join-Path $repoRoot 'web')
        try {
            & $node.Source $vite --host 127.0.0.1 --port $WebPort --strictPort
        } finally {
            Pop-Location
        }
    }

    if ($LASTEXITCODE -ne 0) {
        throw "$Service exited with code $LASTEXITCODE. See the service log above."
    }
} finally {
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
    Pop-Location
}

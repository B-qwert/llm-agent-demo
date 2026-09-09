param([ValidateSet('init','up','check','llm','stop','status')][string]$Action = 'up')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
function Invoke-CheckedDocker {
    & docker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
if ($Action -eq 'init') {
    & python scripts/init_env.py
    if ($LASTEXITCODE -ne 0) { throw 'Environment initialization failed.' }
    exit 0
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI missing. Install/start Docker Desktop and reopen PowerShell.'
}
if (-not (Test-Path -LiteralPath '.env')) { throw 'Run python scripts/init_env.py first.' }
switch ($Action) {
    'up' {
        Invoke-CheckedDocker info --format '{{.OSType}}'
        Invoke-CheckedDocker compose config --quiet
        Invoke-CheckedDocker compose up -d --wait --wait-timeout 360
        Invoke-CheckedDocker compose --profile tools build check
        Invoke-CheckedDocker compose --profile tools run --rm check --only databases --report reports/databases.json
    }
    'check' { Invoke-CheckedDocker compose --profile tools run --rm check --only all }
    'llm' { Invoke-CheckedDocker compose --profile tools run --rm check --only llm --report reports/llm.json }
    'stop' { Invoke-CheckedDocker compose stop }
    'status' { Invoke-CheckedDocker compose ps }
}

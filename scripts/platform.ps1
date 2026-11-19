param([ValidateSet('start','prepare','stop','status','logs')][string]$Action='start',
      [ValidateSet('method','character','ast','token','paragraph')][string]$Strategy='method',
      [int]$ChunkSize=800,[int]$ChunkOverlap=100)
$ErrorActionPreference='Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$platformDocker = (Get-Command docker -ErrorAction SilentlyContinue).Source
if (-not $platformDocker -and (Test-Path -LiteralPath 'D:\DevTools\DockerDesktop\resources\bin\docker.exe')) {
    $platformDocker='D:\DevTools\DockerDesktop\resources\bin\docker.exe'
}
if (-not $platformDocker) { throw 'Docker CLI not found. Start Docker Desktop and reopen PowerShell.' }
function Run-Docker {
    & $platformDocker @args
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed (exit $LASTEXITCODE)." }
}
if (-not (Test-Path -LiteralPath '.env')) { throw 'Run python scripts/init_env.py and configure .env first.' }
switch ($Action) {
    'start' {
        # Do not recreate existing databases or pull different images just to open the UI.
        Run-Docker compose --profile platform up -d --no-deps platform
        Write-Host 'Open http://127.0.0.1:8765 in your browser.'
    }
    'prepare' {
        Write-Host 'Keep Neo4j, Milvus and Ollama running. Preparing isolated sample indexes...'
        Run-Docker compose --profile platform run --rm --no-deps --entrypoint python platform -m bizcodeqa.platform.prepare --strategy $Strategy --chunk-size $ChunkSize --chunk-overlap $ChunkOverlap
    }
    'stop' { Run-Docker compose --profile platform stop platform }
    'status' { Run-Docker compose --profile platform ps }
    'logs' { Run-Docker compose --profile platform logs --tail 80 platform }
}

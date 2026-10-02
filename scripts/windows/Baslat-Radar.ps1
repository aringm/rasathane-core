param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$radarRoot = Join-Path $repoRoot 'apps\radar'
$runtimeRoot = Join-Path $repoRoot '.local\radar'
$url = 'http://127.0.0.1:8775'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null

function Test-Radar {
    try {
        $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
        return $health.service -eq 'rasathane-dashboard' -and $health.status -eq 'ok'
    } catch { return $false }
}

function Start-RadarInfrastructure {
    $dockerExe = (Get-Command docker -ErrorAction Stop).Source
    & $dockerExe info --format '{{.ServerVersion}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dockerDesktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $dockerDesktop)) { throw 'Docker Desktop bulunamadi.' }
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        $dockerReady = $false
        for ($attempt = 0; $attempt -lt 90; $attempt++) {
            Start-Sleep -Seconds 2
            & $dockerExe info --format '{{.ServerVersion}}' 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
        }
        if (-not $dockerReady) { throw 'Docker Desktop hazir olmadi.' }
    }

    & $dockerExe compose --project-directory $radarRoot up -d --wait postgres redis
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL veya Redis baslatilamadi.' }
}

Start-RadarInfrastructure
if (-not (Test-Radar)) {
    $pythonExe = Join-Path $radarRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Radar Python ortami bulunamadi; uv sync --frozen --all-packages calistirin.' }

    # Shell values override .env without exposing or rewriting provider keys.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:DATABASE_URL = 'postgresql+asyncpg://rasathane:rasathane@127.0.0.1:5435/rasathane'
    $env:REDIS_URL = 'redis://127.0.0.1:6381/0'
    $env:OLLAMA_HOST = 'http://127.0.0.1:11434'
    $env:OLLAMA_MODEL_EMBED = 'qwen3-embedding:0.6b-memory-cpu'
    $env:OLLAMA_MODEL_CHAT = 'gemma4-e2b-qat:latest'
    $env:LOCAL_LLM_PROVIDER = 'ollama'
    # The archived .env points to a Whisper container that is not installed.
    # Use the Python fallback instead of announcing an unavailable HTTP service.
    # Windows PowerShell removes an environment variable assigned an empty string.
    # A space survives inheritance; the app's .strip() resolves it as disabled.
    $env:WHISPER_API_URL = ' '
    $env:RASATHANE_PORT = '8775'
    $env:RASATHANE_NO_BROWSER = '1'
    $env:RASATHANE_ENABLE_CRON = '0'
    $env:RASATHANE_AUTO_BRIEF = '0'
    $server = Start-Process -FilePath $pythonExe -WorkingDirectory $radarRoot -WindowStyle Hidden -PassThru `
        -ArgumentList @('-m', 'uvicorn', 'rasathane_mcp.dashboard.app:create_app', '--factory', '--host', '127.0.0.1', '--port', '8775') `
        -RedirectStandardOutput (Join-Path $runtimeRoot 'stdout.log') `
        -RedirectStandardError (Join-Path $runtimeRoot 'stderr.log')
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        if (Test-Radar) { break }
        if ($server.HasExited) { throw "Radar kapandi; log: $runtimeRoot\stderr.log" }
        Start-Sleep -Seconds 1
    }
    if (-not (Test-Radar)) { throw "Radar hazir olmadi; log: $runtimeRoot\stderr.log" }
    # Python's Windows venv redirector may spawn the actual server as a child.
    $listener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8775 -State Listen
    $listener.OwningProcess | Set-Content -LiteralPath (Join-Path $runtimeRoot 'server.pid')
}
if (-not $NoBrowser) { Start-Process $url }
Write-Output "Rasathane Radar: $url"

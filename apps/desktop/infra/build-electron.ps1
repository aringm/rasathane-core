[CmdletBinding()]
param([switch]$SkipTests, [switch]$ReuseCompiled)
$ErrorActionPreference = 'Stop'
$desktopRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$guiRoot = Join-Path $desktopRoot 'gui'
$package = Get-Content -LiteralPath (Join-Path $guiRoot 'package.json') -Raw | ConvertFrom-Json
$version = $package.version
$releaseDirectory = Join-Path $desktopRoot "releases/$version"
$buildDirectory = Join-Path $guiRoot "dist-electron/$version"
# Önceki release, kullanıcı verisi ve model cache'i build sırasında silinmez.
New-Item -ItemType Directory -Path $releaseDirectory,$buildDirectory -Force | Out-Null
Set-Location $desktopRoot
uv sync --frozen --group content --group intel
if ($LASTEXITCODE -ne 0) { throw 'Engine frozen sync başarısız.' }
Push-Location $guiRoot
try {
  pnpm install --frozen-lockfile
  if ($LASTEXITCODE -ne 0) { throw 'pnpm frozen install başarısız.' }
  pnpm brand
  if ($LASTEXITCODE -ne 0) { throw 'Marka asset build başarısız.' }
  pnpm check
  if ($LASTEXITCODE -ne 0) { throw 'Electron kontrolleri başarısız.' }
} finally { Pop-Location }
if (-not $SkipTests) {
  uv run --frozen --group content --group intel pytest -q
  if ($LASTEXITCODE -ne 0) { throw 'Engine testleri başarısız.' }
}
if (-not $ReuseCompiled) {
  & (Join-Path $PSScriptRoot 'fetch-motor.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Pinned model staging başarısız.' }
  & (Join-Path $PSScriptRoot 'build-worker.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Worker build başarısız.' }
  & (Join-Path $PSScriptRoot 'build-sidecar.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'Sidecar build başarısız.' }
}
foreach ($relative in @('infra/dist/worker/rasathane-worker.exe','infra/dist/ytanaliz-sidecar.exe','infra/vendor/motor/bin/llama-server.exe','infra/vendor/motor/modeller/ner/model.safetensors','infra/vendor/motor/modeller/asr/model.bin')) {
  if (-not (Test-Path -LiteralPath (Join-Path $desktopRoot $relative) -PathType Leaf)) { throw "Dağıtım girdisi eksik: $relative" }
}
uv run --no-sync python (Join-Path $PSScriptRoot 'verify-runtime.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned runtime SHA256 doğrulaması başarısız.' }
uv run --no-sync python -B (Join-Path $PSScriptRoot 'source-offer.py') verify --release
if ($LASTEXITCODE -ne 0) { throw 'Native kaynak erişimi ve yayın makbuzu doğrulanamadı.' }
uv run --no-sync python -B (Join-Path $PSScriptRoot 'verify-source-supplement.py') --release
if ($LASTEXITCODE -ne 0) { throw 'PDF motoru/font kaynak eki ve yayın makbuzu doğrulanamadı.' }
uv run --no-sync python (Join-Path $PSScriptRoot 'build-notices.py')
if ($LASTEXITCODE -ne 0) { throw 'SBOM/lisans envanteri başarısız.' }
Push-Location $guiRoot
try {
  pnpm exec electron-builder --win nsis --x64 "--config.directories.output=$buildDirectory"
  if ($LASTEXITCODE -ne 0) { throw 'Electron/NSIS build başarısız.' }
} finally { Pop-Location }
$artifactName = "Rasathane-Setup-$version-x64.exe"
$artifactPath = Join-Path $buildDirectory $artifactName
$releasePath = Join-Path $releaseDirectory $artifactName
Copy-Item -LiteralPath $artifactPath -Destination $releasePath -Force
$hash = (Get-FileHash -LiteralPath $releasePath -Algorithm SHA256).Hash.ToLowerInvariant()
$manifest = [ordered]@{
  product='Rasathane'; version=$version; publisher='Av. Mehmet Arın Gülüm'; platform='Windows x64'
  framework="Electron $($package.devDependencies.electron)"; artifact=$artifactName; sha256=$hash
  bytes=(Get-Item -LiteralPath $releasePath).Length; source_commit=(git rev-parse HEAD).Trim()
  source_dirty=[bool](git status --porcelain); compiled_reused=[bool]$ReuseCompiled
  sidecar_sha256=(Get-FileHash -LiteralPath (Join-Path $desktopRoot 'infra/dist/ytanaliz-sidecar.exe')).Hash.ToLowerInvariant()
  worker_sha256=(Get-FileHash -LiteralPath (Join-Path $desktopRoot 'infra/dist/worker/rasathane-worker.exe')).Hash.ToLowerInvariant()
  code_signing=(Get-AuthenticodeSignature -LiteralPath $releasePath).Status.ToString()
  model_setup='Pinned SHA256 download in wizard'; ram_profile='ram8, CPU, 4096 context'
  packaged_acceptance='pending'; built_at_utc=(Get-Date).ToUniversalTime().ToString('o')
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseDirectory 'release-manifest.json') -Encoding utf8
"$hash  $artifactName" | Set-Content -LiteralPath (Join-Path $releaseDirectory 'SHA256SUMS.txt') -Encoding ascii
Copy-Item -LiteralPath (Join-Path $desktopRoot 'infra/vendor/licenses/SBOM.cdx.json') -Destination $releaseDirectory -Force
Write-Host "Installer: $releasePath"
Write-Host "SHA256: $hash"
Write-Host 'Paket kullanıcı yolu doğrulaması ayrıca yapılmalıdır; eski kurulum korunmuştur.'

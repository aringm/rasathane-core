[CmdletBinding()]
param([switch]$SkipTests, [switch]$ReuseCompiled, [switch]$Unsigned, [string]$CertificateThumbprint = $env:RASATHANE_SIGN_THUMBPRINT)
$ErrorActionPreference = 'Stop'
$desktopRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$guiRoot = Join-Path $desktopRoot 'gui'
$package = Get-Content -LiteralPath (Join-Path $guiRoot 'package.json') -Raw | ConvertFrom-Json
$version = $package.version
$certificate = $null
$signToolPath = $null
if (-not $Unsigned) {
  $now = Get-Date
  $certificates = @(Get-ChildItem Cert:/CurrentUser/My -CodeSigningCert | Where-Object { $_.HasPrivateKey -and $_.NotBefore -le $now -and $_.NotAfter -gt $now })
  if ($CertificateThumbprint) {
    $thumbprint = ($CertificateThumbprint -replace '\s','').ToUpperInvariant()
    if ($thumbprint -notmatch '^[0-9A-F]{40}$') { throw 'Code signing sertifika kimliği geçersiz.' }
    $certificate = $certificates | Where-Object { $_.Thumbprint -eq $thumbprint } | Select-Object -First 1
  } else {
    $certificate = $certificates | Where-Object { $_.Subject -like '*IOT INN*' } | Sort-Object NotAfter -Descending | Select-Object -First 1
  }
  if (-not $certificate) { throw 'Geçerli code signing sertifikası bulunamadı. Geliştirici paketi için açıkça -Unsigned kullanın.' }
  $signToolPath = (Get-ChildItem "${env:ProgramFiles(x86)}/Windows Kits/10/bin/*/x64/signtool.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1).FullName
  if (-not $signToolPath -or (Get-AuthenticodeSignature -LiteralPath $signToolPath).Status -ne 'Valid') { throw 'Güvenilir Windows SDK SignTool bulunamadı.' }
}
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
$signingEnvironment = @{}
foreach ($name in @('RASATHANE_SIGN_THUMBPRINT','RASATHANE_SIGNTOOL_PATH','RASATHANE_UNSIGNED_BUILD')) { $signingEnvironment[$name] = [Environment]::GetEnvironmentVariable($name,'Process') }
try {
  $env:RASATHANE_UNSIGNED_BUILD = if ($Unsigned) { '1' } else { '0' }
  $env:RASATHANE_SIGN_THUMBPRINT = if ($certificate) { $certificate.Thumbprint } else { '' }
  $env:RASATHANE_SIGNTOOL_PATH = $signToolPath
  pnpm exec electron-builder --win nsis --x64 "--config.directories.output=$buildDirectory" 2>&1 | Tee-Object -Variable builderOutput
  if ($LASTEXITCODE -ne 0) { throw 'Electron/NSIS build başarısız.' }
} finally {
  foreach ($name in $signingEnvironment.Keys) { [Environment]::SetEnvironmentVariable($name,$signingEnvironment[$name],'Process') }
  Pop-Location
}
$artifactName = "Rasathane-Setup-$version-x64.exe"
$artifactPath = Join-Path $buildDirectory $artifactName
$signatureChecks = @()
$signatureEvents = @($builderOutput | ForEach-Object { $line=$_.ToString(); if ($line.StartsWith('RASATHANE_SIGNATURE ')) { $line.Substring(20) | ConvertFrom-Json } })
foreach ($relative in @($artifactName,'win-unpacked/Rasathane.exe','win-unpacked/resources/elevate.exe')) {
  $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $buildDirectory $relative)
  if (-not $Unsigned -and ($signature.Status -ne 'Valid' -or -not $signature.TimeStamperCertificate -or $signature.SignerCertificate.Thumbprint -ne $certificate.Thumbprint)) { throw "Paket imzası/zaman damgası doğrulanamadı: $relative" }
  $signatureChecks += [ordered]@{ file=$relative; status=$signature.Status.ToString(); timestamp=[bool]$signature.TimeStamperCertificate; signer_thumbprint=$signature.SignerCertificate.Thumbprint }
}
if (-not $Unsigned) {
  $uninstallerName = "Rasathane-Setup-$version-x64.__uninstaller.exe"
  $uninstallerPath = [IO.Path]::GetFullPath((Join-Path $buildDirectory $uninstallerName))
  $uninstallerProof = @($signatureEvents | Where-Object { $_.path -eq $uninstallerPath -and $_.verified -eq $true -and $_.rfc3161_requested -eq $true -and $_.sha256 -match '^[a-f0-9]{64}$' })
  if ($uninstallerProof.Count -ne 1) { throw 'NSIS kaldırıcı imzasının build makbuzu doğrulanamadı.' }
  $signatureChecks += [ordered]@{ file=$uninstallerName; status='VerifiedDuringBuild'; verification='signtool /pa /all'; rfc3161_requested=$true; sha256=$uninstallerProof[0].sha256; signer_thumbprint=$certificate.Thumbprint }
}
# Pinned upstream binary'ler ve frozen motor imzalama sırasında değiştirilmez.
foreach ($pair in @(@('infra/dist/ytanaliz-sidecar.exe','win-unpacked/resources/sidecar/ytanaliz-sidecar.exe'),@('infra/dist/worker/rasathane-worker.exe','win-unpacked/resources/worker/rasathane-worker.exe'),@('infra/vendor/tooling/typst/typst.exe','win-unpacked/resources/tooling/typst/typst.exe'))) {
  if ((Get-FileHash -LiteralPath (Join-Path $desktopRoot $pair[0])).Hash -ne (Get-FileHash -LiteralPath (Join-Path $buildDirectory $pair[1])).Hash) { throw "Pinned/frozen binary değişti: $($pair[1])" }
}
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
  signature_checks=$signatureChecks; unsigned_developer_build=[bool]$Unsigned
  model_setup='Pinned SHA256 download in wizard'; ram_profile='ram8, CPU, 4096 context'
  packaged_acceptance='pending'; built_at_utc=(Get-Date).ToUniversalTime().ToString('o')
}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseDirectory 'release-manifest.json') -Encoding utf8
"$hash  $artifactName" | Set-Content -LiteralPath (Join-Path $releaseDirectory 'SHA256SUMS.txt') -Encoding ascii
Copy-Item -LiteralPath (Join-Path $desktopRoot 'infra/vendor/licenses/SBOM.cdx.json') -Destination $releaseDirectory -Force
Write-Host "Installer: $releasePath"
Write-Host "SHA256: $hash"
Write-Host 'Paket kullanıcı yolu doğrulaması ayrıca yapılmalıdır; eski kurulum korunmuştur.'

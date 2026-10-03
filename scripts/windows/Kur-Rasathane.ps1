[CmdletBinding()]
param([switch]$Launch, [switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$package = Get-Content -LiteralPath (Join-Path $repoRoot 'apps/desktop/gui/package.json') -Raw | ConvertFrom-Json
$releaseRoot = Join-Path $repoRoot "apps/desktop/releases/$($package.version)"
$manifest = Get-Content -LiteralPath (Join-Path $releaseRoot 'release-manifest.json') -Raw | ConvertFrom-Json
$expectedName = "Rasathane-Setup-$($package.version)-x64.exe"
if ($manifest.artifact -ne $expectedName -or $manifest.version -ne $package.version -or $manifest.sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'Kurulum manifest sözleşmesi geçersiz.'
}
$installer = Join-Path $releaseRoot $expectedName
if ((Get-Item -LiteralPath $installer).Length -ne $manifest.bytes -or (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.sha256) {
    throw 'Kurulum dosyasının boyutu veya SHA256 değeri manifest ile eşleşmiyor.'
}
if ($VerifyOnly) { Write-Output "Doğrulandı: $installer"; return }
if ($manifest.packaged_acceptance -ne 'passed') { throw 'Gerçek paket kabulü tamamlanmadan kurulum yapılmaz.' }
if (Get-Process Rasathane -ErrorAction SilentlyContinue) { throw 'Kurulumdan önce açık Rasathane penceresini kapatın.' }
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs/Rasathane'
$process = Start-Process -FilePath $installer -ArgumentList '/S',"/D=$installRoot" -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath (Join-Path $installRoot 'Rasathane.exe') -PathType Leaf)) {
    throw "Rasathane kurulumu doğrulanamadı; exit code $($process.ExitCode)."
}
& (Join-Path $PSScriptRoot 'Kur-Kisayollar.ps1')
if ($Launch) { & (Join-Path $PSScriptRoot 'Baslat-Rasathane.ps1') }
Write-Output (Join-Path $installRoot 'Rasathane.exe')

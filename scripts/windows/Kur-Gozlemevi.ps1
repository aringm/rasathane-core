param([switch]$Launch)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$payload = Join-Path $repoRoot 'apps\desktop\gui\dist-electron\win-unpacked'
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\RasathaneGozlemevi\0.4.1'
$sourceExe = Join-Path $payload 'Rasathane.exe'
if (-not (Test-Path -LiteralPath $sourceExe)) { throw 'Gozlemevi 0.4.1 paketi bulunamadi.' }
if (Get-Process Rasathane -ErrorAction SilentlyContinue) { throw 'Kurulumdan once acik Gozlemevi penceresini kapatin.' }

New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
foreach ($file in Get-ChildItem -LiteralPath $payload -Recurse -File) {
    $relative = $file.FullName.Substring($payload.Length).TrimStart('\')
    $target = Join-Path $installRoot $relative
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    if ($file.Extension -eq '.gguf') {
        # Immutable model files share disk blocks on the same NTFS volume.
        if (-not (Test-Path -LiteralPath $target)) {
            New-Item -ItemType HardLink -Path $target -Target $file.FullName | Out-Null
        }
    } else {
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}

$installedExe = Join-Path $installRoot 'Rasathane.exe'
& (Join-Path $PSScriptRoot 'Kur-Kisayollar.ps1')
if ($Launch) { & (Join-Path $PSScriptRoot 'Baslat-Gozlemevi.ps1') }
Write-Output $installedExe

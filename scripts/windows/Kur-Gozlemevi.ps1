param([switch]$Launch)
$ErrorActionPreference = 'Stop'
Write-Warning 'Gözlemevi, birleşik Rasathane ürününe taşındı. Güncel kurulum kullanılıyor.'
& (Join-Path $PSScriptRoot 'Kur-Rasathane.ps1') -Launch:$Launch

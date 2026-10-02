$ErrorActionPreference = 'Stop'
$program = Join-Path $env:LOCALAPPDATA 'Programs/Rasathane/Rasathane.exe'
if (-not (Test-Path -LiteralPath $program -PathType Leaf)) {
    throw 'Birleşik Rasathane kurulumu bulunamadı. Önce Kur-Rasathane.ps1 çalıştırın.'
}
# Kullanıcının başlatıcısı görünür masaüstü uygulamasını açar.
Start-Process -FilePath $program

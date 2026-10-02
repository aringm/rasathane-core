$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$motorRoot = Join-Path $repoRoot 'apps\desktop'
$installedExe = Join-Path $env:LOCALAPPDATA 'Programs\RasathaneGozlemevi\0.4.1\Rasathane.exe'
if (-not (Test-Path -LiteralPath $installedExe)) { throw 'Gozlemevi kurulu degil; Kur-Gozlemevi.ps1 calistirin.' }
$env:YT_MOTOR_KOK = $motorRoot
$env:YT_ASR_PYTHON = Join-Path $motorRoot '.venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
if (-not $env:HF_HOME -and (Test-Path -LiteralPath 'D:\huggingface')) { $env:HF_HOME = 'D:\huggingface' }
Start-Process -FilePath $installedExe -WorkingDirectory (Split-Path $installedExe -Parent)

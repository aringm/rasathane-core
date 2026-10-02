$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$shell = New-Object -ComObject WScript.Shell
$menuRoot = Join-Path ([Environment]::GetFolderPath('Programs')) 'Rasathane'
$psExe = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$iconExe = Join-Path $env:LOCALAPPDATA 'Programs\RasathaneGozlemevi\0.4.1\Rasathane.exe'
New-Item -ItemType Directory -Path $menuRoot -Force | Out-Null
foreach ($app in @(
    @{ Name='Rasathane Gözlemevi'; Script='Baslat-Gozlemevi.ps1'; Description='Rasathane 0.4.1 — Yerel İçerik Gözlemevi' },
    @{ Name='Rasathane Radar'; Script='Baslat-Radar.ps1'; Description='Rasathane — Hukuk ve AI Radarı' }
)) {
    $launchScript = Join-Path $PSScriptRoot $app.Script
    foreach ($shortcutRoot in @([Environment]::GetFolderPath('Desktop'), $menuRoot)) {
        $link = $shell.CreateShortcut((Join-Path $shortcutRoot ($app.Name + '.lnk')))
        $link.TargetPath = $psExe
        $link.Arguments = '-NoProfile -WindowStyle Hidden -File "' + $launchScript + '"'
        $link.WorkingDirectory = $repoRoot
        $link.IconLocation = "$iconExe,0"
        $link.Description = $app.Description
        $link.WindowStyle = 7
        $link.Save()
    }
}

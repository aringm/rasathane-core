$ErrorActionPreference = 'Stop'
$program = Join-Path $env:LOCALAPPDATA 'Programs/Rasathane/Rasathane.exe'
if (-not (Test-Path -LiteralPath $program -PathType Leaf)) { throw 'Rasathane kurulumu bulunamadı.' }
$shell = New-Object -ComObject WScript.Shell
foreach ($shortcutRoot in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $link = $shell.CreateShortcut((Join-Path $shortcutRoot 'Rasathane.lnk'))
    $link.TargetPath = $program
    $link.WorkingDirectory = Split-Path $program -Parent
    $link.IconLocation = "$program,0"
    $link.Description = 'Rasathane — yerel kaynak takip, analiz ve araştırma'
    $link.Save()
}

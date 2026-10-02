$ErrorActionPreference = 'Stop'
$desktopRoot = Split-Path -Parent $PSScriptRoot
$workerProject = Join-Path $PSScriptRoot 'worker-runtime'
uv sync --project $workerProject --frozen
if ($LASTEXITCODE -ne 0) { throw 'Worker dependency sync başarısız.' }
$workerPython = Join-Path $workerProject '.venv/Scripts/python.exe'
& $workerPython -m PyInstaller --onedir --name rasathane-worker --paths (Join-Path $desktopRoot 'core') `
  --hidden-import ytcore.router.ner_worker --hidden-import ytcore.transcript.asr_worker `
  --hidden-import transformers.models.bert.modeling_bert --hidden-import transformers.models.bert.tokenization_bert_fast `
  --collect-all faster_whisper --collect-all tokenizers --copy-metadata torch --copy-metadata transformers `
  --exclude-module whisperx --exclude-module torchvision --exclude-module torchaudio --exclude-module tkinter `
  --distpath (Join-Path $PSScriptRoot 'worker-dist') --workpath (Join-Path $PSScriptRoot 'worker-build') `
  --specpath $PSScriptRoot --noconfirm (Join-Path $PSScriptRoot 'worker_entry.py')
if ($LASTEXITCODE -ne 0) { throw 'Worker build başarısız.' }
$workerDestination = Join-Path $PSScriptRoot 'dist/worker'
if (Test-Path -LiteralPath $workerDestination) {
  $resolvedDestination = [IO.Path]::GetFullPath($workerDestination)
  $expectedDestination = [IO.Path]::GetFullPath((Join-Path $desktopRoot 'infra/dist/worker'))
  if ($resolvedDestination -ne $expectedDestination -or (Get-Item -LiteralPath $workerDestination).Attributes.HasFlag([IO.FileAttributes]::ReparsePoint)) { throw 'Worker staging sınırı doğrulanamadı.' }
  Remove-Item -LiteralPath $workerDestination -Recurse -Force
}
New-Item -ItemType Directory -Path $workerDestination -Force | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot 'worker-dist/rasathane-worker/*') -Destination $workerDestination -Recurse -Force
Write-Host "Worker hazır: $workerDestination"

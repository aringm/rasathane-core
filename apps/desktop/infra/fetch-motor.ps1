# Rasathane 0.5: binary+NER/ASR staging; GGUF ilk kurulumda pinned katalogdan indirilir.
$ErrorActionPreference = 'Stop'
$desktopRoot = Split-Path -Parent $PSScriptRoot
$workerProject = Join-Path $PSScriptRoot 'worker-runtime'
uv sync --project $workerProject --frozen
if ($LASTEXITCODE -ne 0) { throw 'Worker frozen sync başarısız.' }
uv run --project $workerProject --no-sync python (Join-Path $PSScriptRoot 'prepare-runtime.py')
if ($LASTEXITCODE -ne 0) { throw 'Pinned runtime hazırlığı başarısız.' }

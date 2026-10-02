# PyInstaller sidecar build — core+mcp tek exe.
# Muhakeme dersi: engine degisince rebuild SART; lazy-modul hidden-import deklare.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# DEGISMEZ #2 (<=16GB): exe torch/whisperx ICERMEZ — ASR ayri proses (asr group).
# 'uv run --group asr ...' onceki cagrilarindan .venv'de kalan ML stack exe'ye sizmasin
# diye build ONCESI env'i senkronla. Faz 2: --group content (yake/docxtpl TORCH'SUZ — exe'ye
# girmeli; embedding/LLM/faithfulness Ollama-HTTP oldugu icin torch HALA yok). asr HARIC.
uv sync --frozen --group content --group intel
if ($LASTEXITCODE -ne 0) { throw "uv sync başarısız oldu (exit $LASTEXITCODE)." }

$hidden = @(
  "--hidden-import", "langgraph.checkpoint.sqlite",
  "--hidden-import", "fastmcp",
  "--hidden-import", "ytcore.pipeline.api",
  # Rasathane ortak kaynak adapter'ları (graph içinde lazy import).
  "--collect-submodules", "rasathane",
  "--hidden-import", "ytmcp.server",
  # Gömülü llama.cpp backend'i — llm_al/embedding_al backend seçimini fonksiyon-içi
  # (lazy) importla yapar; PyInstaller statik analizi kaçırır -> collect zorunlu.
  "--collect-submodules", "ytcore.local",

  # Faz 1: transcript node + fetcher_al() lazy-import eder (PyInstaller fonksiyon-içi
  # importları statik analizde kaçırabilir) -> tüm transcript submodüllerini topla.
  "--collect-submodules", "ytcore.transcript",
  "--hidden-import", "ytcore.output.transcript_yaz",
  "--hidden-import", "ytcore.output.kaynak_yaz",
  # Faz 2: icerik node'lari + output yazicilari graph/_output_node icinde lazy-import.
  "--collect-submodules", "ytcore.content",
  "--hidden-import", "ytcore.output.ceviri_yaz",
  "--hidden-import", "ytcore.output.dokum_yaz",
  "--hidden-import", "ytcore.output.typst_runtime",
  "--hidden-import", "ytcore.output.ozet_yaz",
  "--hidden-import", "ytcore.infra.embedding",
  "--hidden-import", "ytcore.pipeline.state",
  # Faz 2 torch'suz ML kutuphaneleri. YAKE stopwords DATA dosyalari (StopwordsList/*.txt)
  # bundle edilmeli -> --collect-all (submodul+data); yoksa frozen exe keyword_cikar patlar.
  "--collect-all", "yake",
  "--hidden-import", "docx",
  "--hidden-import", "docxtpl",
  "--collect-submodules", "ollama",
  # yt-dlp lazy extractor'lari (gercek altyazi yolu icin) — collect zorunlu.
  "--collect-submodules", "yt_dlp",
  # Faz 3 zeka node'lari + cikti yazicilari (graph/_output_node icinde lazy-import).
  "--collect-submodules", "ytcore.intel",
  "--hidden-import", "ytcore.output.degerleme_yaz",
  "--hidden-import", "ytcore.output.kisisel_yaz",
  "--hidden-import", "ytcore.output.factcheck_yaz",
  "--hidden-import", "ytcore.infra.index",
  "--hidden-import", "ytcore.infra.rrf",
  # Faz 3 hibrit index = LanceDB (Rust+pyarrow, TORCH'SUZ). lazy-import (LanceFtsRrfStore
  # icinde) -> collect zorunlu (yoksa gercek-index exe'de patlar; fixture selftest bunu
  # gormez). pyarrow native binding'leri PyInstaller hook-pyarrow ile otomatik gelir
  # (--collect-submodules pyarrow tests'i de cekip bloat/error yapar -> hook'a birak).
  "--collect-all", "lancedb",
  # Faz 4 uretim node'lari (harita/markmap) + cikti graph/_output_node sonrasi lazy-import.
  # SAF-Python+JS (torch'suz) -> exe'ye girer. TTS exe-DISI (piper/onnxruntime exclude).
  "--collect-submodules", "ytcore.uretim",
  "--hidden-import", "ytcore.uretim.harita",
  "--hidden-import", "ytcore.uretim.markmap",
  "--hidden-import", "ytcore.uretim.node",
  # Faz 5: NER engine-tarafi (saf-python seam; worker AYRI proses/exe-DISI) + gercek
  # CloudClient + MCP adim-tool'lari — hepsi lazy-import -> hidden-import sart.
  "--hidden-import", "ytcore.router.ner",
  "--hidden-import", "ytcore.router.cloud_client",
  "--hidden-import", "ytmcp.tools"
)

# Faz 2: glossary CSV Path(__file__).parent'tan okunur -> frozen exe'ye data olarak bundle
# (yoksa varsayilan_glossary() FileNotFoundError; ceviri yolu icin gerekli). --specpath infra
# add-data kaynagini spec dizinine gore cozdugu icin ABSOLUTE yol ($root) ver.
$glossarySrc = Join-Path $root "core/ytcore/content/glossary_data/hukuk_terimleri.csv"
# Faz 4: markmap vendored JS (d3+markmap-view) Path(__file__).parent/assets'ten okunur ->
# frozen exe'ye DATA olarak bundle (yoksa markmap_html FileNotFoundError; harita yolu icin).
$markmapSrc = Join-Path $root "core/ytcore/uretim/assets"
$datas = @(
  "--add-data", "$root/core/ytcore/uretim/windows-tts.ps1;ytcore/uretim",
  "--add-data", "$glossarySrc;ytcore/content/glossary_data",
  "--add-data", "$markmapSrc;ytcore/uretim/assets",
  # Faz 5 (review tur-1): fastmcp __init__ surumunu importlib.metadata'dan okur -> dist-info
  # bundle'da yoksa stdio/http modu import ANINDA coker (selftest bu yolu gormuyordu; http
  # smoke testi yakaladi). copy-metadata sart.
  "--copy-metadata", "fastmcp"
)

# ASR stack AYRI PROSES (degismez #2: ≤16GB) — exe'ye GIRMEZ. asr_worker.py torch'u
# yalniz fonksiyon-ici import eder; yine de acikca disla (yalin exe + erken hata yok).
$excludes = @(
  "--exclude-module", "torch",
  "--exclude-module", "whisperx",
  "--exclude-module", "faster_whisper",
  "--exclude-module", "pyannote",
  # Faz 4: Piper TTS exe-DISI (ASR deseni — onnxruntime+voice exe'yi sisirir, <200MB asar).
  # selftest FakeTTS kullanir; gercek Piper AYRI PROSES (tts_worker, .venv python). uretim
  # grubu sync EDILMEZ (yukarida). tts_worker exe'ye GIRMEZ (ner_worker gibi; --collect-submodules
  # ytcore.uretim onu cekmesin diye acikca disla — harici .venv python'dan import edilir).
  "--exclude-module", "piper",
  "--exclude-module", "onnxruntime",
  "--exclude-module", "ytcore.uretim.tts_worker",
  # Faz 5: NER worker exe-DISI (ASR deseni — transformers+torch ayri proses; ner grubu
  # zaten sync edilmiyor, yine de acikca disla: yalin exe + erken hata yok).
  "--exclude-module", "transformers",
  "--exclude-module", "ytcore.router.ner_worker"
)

uv run python -m PyInstaller --onefile --name ytanaliz-sidecar `
  --paths core --paths mcp `
  @hidden `
  @datas `
  @excludes `
  --distpath infra/dist --workpath infra/build --specpath infra `
  --noconfirm `
  infra/sidecar_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller sidecar build başarısız oldu (exit $LASTEXITCODE)." }

Write-Host "Sidecar: infra/dist/ytanaliz-sidecar.exe"

# Tauri externalBin: target-triple isimli kopya (GUI sidecar'i senkron tut).
# LEGACY yol: rustc kurulu degilse (Electron tek paketleme hatti) atla — build'i bozma.
$rustcCmd = Get-Command rustc -ErrorAction SilentlyContinue
if (-not $rustcCmd) {
  Write-Host "rustc bulunamadi — legacy Tauri sidecar kopyasi atlaniyor (Electron etkilenmez)."
} else {
  $triple = (rustc -vV | Select-String '^host:').ToString().Split(' ')[1]
  if ($LASTEXITCODE -ne 0 -or -not $triple) { throw "Rust target triple belirlenemedi." }
  $binDir = Join-Path $root "gui/src-tauri/binaries"
  New-Item -ItemType Directory -Force -Path $binDir | Out-Null
  $dest = Join-Path $binDir "ytanaliz-sidecar-$triple.exe"
  Copy-Item "infra/dist/ytanaliz-sidecar.exe" $dest -Force
  Write-Host "Tauri sidecar: $dest"
}

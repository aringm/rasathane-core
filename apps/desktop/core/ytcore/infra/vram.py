from __future__ import annotations

# Cephe-doğrulanmış VRAM sabitleri (ANA-RAPOR §6.2-6.3, A03 düzeltme).
# Faz 0 dokümante eder; Faz 1 kendi RTX 3090'da empirik ölçer.
VRAM_BUTCE: dict[str, float] = {
    "limit_gb": 16.0,
    "bge_m3_yukleme_gb": 1.1,
    "bge_m3_batch256_gb": 5.7,  # A03 düzeltme: NOT 1.5 — global batch sınırı şart
    "qwen3_8b_gb": 5.0,
    "qwen3_14b_32k_gb": 13.6,
    "qwen25_14b_gb": 9.0,
    "whisper_turbo_int8_gb": 1.5,
    # Faz 1: WhisperX TR align (wav2vec2-xls-r-300m) — ASR worker'da ayrı proses.
    "whisperx_align_gb": 1.2,
    # Faz 2 EMPİRİK (ollama ps + nvidia-smi, RTX 3090, 2026-06-08):
    "qwen25_14b_8k_olculen_gb": 11.0,  # @num_ctx=8192 (ollama ps "11 GB")
    "qwen25_14b_32k_olculen_gb": 17.0,  # @num_ctx=32768 — TEK 16GB GPU'ya SIĞMAZ → num_ctx cap
    "bge_m3_olculen_gb": 0.87,  # bge-m3:latest yüklü (ollama ps "873 MB")
    # qwen2.5:14b@8K (11) + bge-m3 (0.87) = ~11.9GB < 16 → Faz 2 swap GEREKMEDİ.
    # Faz 3 EMPİRİK (ollama ps, RTX 3090, 2026-06-08): YENİ MODEL YOK. verdict/claim/bellek-
    # çıkarım hepsi qwen2.5:14b (zaten resident) reuse; bge-m3 index/novelty embedding reuse.
    # LanceDB = CPU/disk/pyarrow (0 GPU). Toplam HÂLÂ ~11.9GB < 16 (Faz 2 ile aynı bütçe).
    "faz3_ek_model_gb": 0.0,  # değişmez #2: Faz 3 zeka katmanı GPU bütçesini büyütmedi
    # Faz 4 (üretim): harita LLM = qwen2.5:14b REUSE (yeni model YOK); Piper TTS = CPU/onnx
    # (0 GPU); markmap render = 0 GPU; cloud TTS = VRAM yok. → ≤16GB EK YÜK getirmez.
    "faz4_ek_model_gb": 0.0,  # değişmez #2: üretim/sunum GPU bütçesini büyütmedi
    # Faz 5 (hibrit servis): NER = bert-base-turkish (~110M) CPU'da AYRI PROSES (device=-1 →
    # 0 GPU); cloud verdict = Anthropic API (VRAM yok); complexity = saf-python; MCP tool'ları
    # mevcut modelleri reuse eder. → ≤16GB EK YÜK getirmez.
    "faz5_ek_model_gb": 0.0,  # değişmez #2: NER CPU + cloud VRAM'siz — bütçe büyümedi
}

HOT_SWAP_PROTOKOL = (
    "Faz 2 EMPİRİK (≤16GB DOĞRULANDI): qwen2.5:14b @num_ctx=8192 = 11GB + bge-m3 873MB "
    "= ~11.9GB < 16GB → aynı anda resident, manuel hot-swap GEREKMEDİ (Ollama keep_alive). "
    "num_ctx CAP ŞART: qwen2.5:14b @32K = 17GB tek 16GB GPU'ya SIĞMAZ "
    "(config.ollama_num_ctx=8192). "
    "Faz 2 ML TORCH-FREE: embedding/çeviri/özet/faithfulness hepsi Ollama-HTTP — torch ana "
    "engine'e/exe'ye girmez (exe 65MB). Whisper turbo int8 + WhisperX align AYRI PROSES "
    "(asr_worker). Özet/çeviri/judge=Qwen2.5-14B (TurkBench SM %75 > Qwen3-14B %68.3 — A04). "
    "Faz 3 EMPİRİK: zeka katmanı (değerleme/kişisel/fact-check) YENİ MODEL eklemedi — "
    "verdict/claim/bellek qwen2.5:14b reuse, embedding bge-m3 reuse, LanceDB CPU/disk (0 GPU) "
    "→ toplam ~11.9GB < 16GB (Faz 2 ile AYNI). torch-free korundu "
    "(lancedb Rust+pyarrow; exe 144MB). "
    "Faz 4 EMPİRİK: üretim/sunum YENİ MODEL eklemedi — harita LLM qwen2.5:14b reuse, "
    "Piper TTS CPU/onnxruntime (0 GPU, exe-DIŞI = ASR deseni), markmap render 0 GPU, cloud "
    "TTS VRAM yok → toplam HÂLÂ ~11.9GB < 16GB. Piper/onnxruntime exe'ye GİRMEZ (<200MB guard). "
    "Faz 5: NER bert-base-turkish CPU AYRI PROSES (device=-1, 0 GPU; transformers/torch "
    "exe-DIŞI), cloud verdict VRAM'siz, complexity saf-python → bütçe yine ~11.9GB < 16GB."
)


def _parse_param_b(parametre: str) -> float | None:
    """Ollama parameter_size string'ini milyar-parametreye çevir ('14.8B'->14.8,
    '566.70M'->0.567, '36.0B'->36.0). Bilinmeyen/boş format -> None."""
    if not parametre:
        return None
    s = parametre.strip().upper().replace(",", ".")
    try:
        if s.endswith("B"):
            return float(s[:-1])
        if s.endswith("M"):
            return float(s[:-1]) / 1000.0
        return float(s) / 1e9  # ham parametre adedi -> milyar
    except ValueError:
        return None


def vram_tahmin_gb(parametre: str, num_ctx: int = 8192) -> tuple[float | None, str]:
    """Ollama modelinin TAHMİNİ VRAM'i (GB) + durum bayrağı. KESİN DEĞİL — Q4 ağırlık +
    KV-cache kaba heuristiği, qwen2.5:14b@8K=11GB ölçülen ankoruna (VRAM_BUTCE) kalibre.

    durum: 'guvenli' (<=limit-3), 'sinir' (limit-3..limit), 'asar' (>limit), 'bilinmiyor'
    (parse edilemedi). Değişmez #2'yi (<=16GB) KULLANICIYA yüzeyler — sert blok DEĞİL,
    27B+ seçimde bilgilendirici uyarı (avukatın dual-3090'ı 48GB; num_ctx cap=8192 tavan)."""
    param_b = _parse_param_b(parametre)
    if param_b is None:
        return None, "bilinmiyor"
    agirlik = param_b * 0.65  # Q4_K_M ~0.6-0.65 GB/B (ankor: 14.8B@8K ~11GB ölçülen)
    kv = param_b * 0.085 * (max(num_ctx, 0) / 8192)  # KV cache ~ctx lineer, param-ölçekli
    tahmin = round(agirlik + kv, 1)
    limit = VRAM_BUTCE["limit_gb"]
    if tahmin <= limit - 3:
        durum = "guvenli"
    elif tahmin <= limit:
        durum = "sinir"
    else:
        durum = "asar"
    # 8192 üstü ctx ankor-dışı: formül hafife alır (14b@32K ölçülen 17GB) →
    # en az 'sinir'e zorla (review LOW; default 8192 cap normalde tetiklemez).
    if num_ctx > 8192 and durum == "guvenli":
        durum = "sinir"
    return tahmin, durum


def bge_m3_batch_guvenli(batch: int, marj_gb: float = 0.5) -> bool:
    """bge-m3 verilen batch'te EN DAR senaryoda 16GB'a sığar mı?

    En dar senaryo = eş-zamanlı Qwen3-14B@32K (13.6GB) swap penceresi. Bütçe =
    limit - 14B - marj (~1.9GB) → batch'i etkin sınırlar (batch-256=5.7GB sığmaz).
    Faz 1 kendi RTX 3090'da empirik ölçer; bu kaba tahmin global batch sınırı kuralıdır.
    """
    butce = VRAM_BUTCE["limit_gb"] - VRAM_BUTCE["qwen3_14b_32k_gb"] - marj_gb
    yukleme = VRAM_BUTCE["bge_m3_yukleme_gb"]
    tahmin = yukleme + (VRAM_BUTCE["bge_m3_batch256_gb"] - yukleme) * (batch / 256)
    return tahmin <= butce

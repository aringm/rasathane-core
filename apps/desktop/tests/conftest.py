from __future__ import annotations

import pytest
from ytcore.config import GOZLEM_KOKU_ADI


@pytest.fixture(autouse=True)
def _hizli_test_varsayilanlari(monkeypatch: pytest.MonkeyPatch):
    """Testler hızlı/deterministik: pipeline gerçek Ollama'ya gitmesin.

    Gerçek round-trip kanıtı dedicated testlerde (test_ollama_ping +
    test_pipeline_ollama_entegrasyonu). Tekil testler bu varsayılanları override edebilir.
    """
    monkeypatch.setenv("YT_OLLAMA_PING", "0")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "0")
    # Faz 1: pipeline testleri ağsız fixture ile koşar (clean = PII'siz temiz TR altyazı).
    # PII/altyazi_yok testleri bu env'i override eder.
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")
    # Faz 2: içerik hattı (çeviri/döküm/özet) hermetik — fake LLM/embedding (Ollama'sız,
    # torch'suz, ağsız). Gerçek model testleri @pytest.mark.ollama (default koşuda atla).
    monkeypatch.setenv("YT_LLM_FIXTURE", "1")
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")
    # Faz 3: index/bellek/web hermetik (fake — ağsız/torch'suz/LanceDB'siz/anahtarsız).
    monkeypatch.setenv("YT_INDEX_FIXTURE", "1")
    monkeypatch.setenv("YT_MEMORY_FIXTURE", "1")
    monkeypatch.setenv("YT_WEBSEARCH_FIXTURE", "1")
    # Faz 4: TTS hermetik (FakeTTS — Piper/onnxruntime/ses-modeli YOK, cloud anahtarsız).
    monkeypatch.setenv("YT_TTS_FIXTURE", "1")
    # Faz 5: NER hermetik (FakeNER — torch'suz/modelsiz). Gerçek model @pytest.mark.ner.
    monkeypatch.setenv("YT_NER_FIXTURE", "1")
    # Faz 7b: Firecrawl default-localhost (127.0.0.1:3002) hermetik testte KAPALI — gerçek
    # probe/arama sızmasın (web zaten YT_WEBSEARCH_FIXTURE ile fake). Tekil test override eder.
    monkeypatch.setenv("YT_FIRECRAWL_URL", "")


@pytest.fixture
def tmp_output_base(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Çıktı kökünü geçici dizine yönlendir (Masaüstü'ne yazma).

    Ad, gerçek gözlem kökünü taklit eder (çift boşluk dâhil) — yol boşluklarına duyarlı
    regresyonlar testte de görünsün. Varsayılan/legacy seçimi burada değil, YT_OUTPUT_BASE
    açıkça set edildiği için devre dışı; o mantık `tests/test_gozlem_koku.py` içinde.
    """
    base = tmp_path / GOZLEM_KOKU_ADI
    base.mkdir()
    monkeypatch.setenv("YT_OUTPUT_BASE", str(base))
    return base

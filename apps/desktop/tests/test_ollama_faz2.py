from __future__ import annotations

import pytest
from ytcore.content.ceviri import cevir
from ytcore.content.faithfulness import faithfulness
from ytcore.content.llm import OllamaLLM
from ytcore.content.ozet import ozetle
from ytcore.infra.embedding import BgeM3Provider

# Gerçek Ollama (bge-m3 + qwen2.5:14b) gerektirir → @pytest.mark.ollama (default koşuda atla).
pytestmark = pytest.mark.ollama


def test_bge_m3_gercek_embed():
    v = BgeM3Provider().embed(["sözleşme hukuku", "borçlar hukuku"])
    assert len(v) == 2
    assert len(v[0]) > 100  # bge-m3 1024-dim
    # iki ilişkili hukuk terimi makul benzerlik (kosinüs > 0.3)
    benz = sum(a * b for a, b in zip(v[0], v[1], strict=False))
    norm0 = sum(a * a for a in v[0]) ** 0.5
    norm1 = sum(b * b for b in v[1]) ** 0.5
    assert (benz / (norm0 * norm1)) > 0.3


def test_qwen_ceviri_gercek():
    out = cevir(
        "This contract is legally binding between the parties.", OllamaLLM(model="qwen2.5:14b")
    )
    assert out.strip()
    assert len(out) > 5  # TR çıktı üretildi


def test_qwen_ozet_gercek():
    metin = (
        "Sözleşme hukuku borçlar hukukunun temelidir. İrade serbestisi modern borçlar "
        "hukukunun çekirdeğidir. Taraflar serbestçe sözleşme yapabilir. Ancak kamu düzeni "
        "ve ahlaka aykırı sözleşmeler geçersizdir. Tazminat hukuku ihlal halinde devreye girer. "
    ) * 3
    sonuc = ozetle(metin, OllamaLLM(model="qwen2.5:14b"), BgeM3Provider())
    assert sonuc["detay"].strip()
    assert sonuc["kisa"].strip()


def test_faithfulness_gercek_judge():
    kaynak = "Sözleşme hukuku borçlar hukukunun temelidir. İrade serbestisi önemlidir."
    # destekli iddia → yüksek skor
    skor, durum = faithfulness(
        "Sözleşme hukuku borçlar hukukunun temelidir.", kaynak, OllamaLLM(model="qwen2.5:14b")
    )
    assert skor >= 0.5


def test_pipeline_gercek_ollama_icerik(tmp_output_base, tmp_path, monkeypatch):
    # review MED #12: içerik hattı seam+graph entegrasyonu GERÇEK Ollama ile (fixture transcript;
    # önceki 'E2E' testi autouse fixture yüzünden FAKE koşuyordu). LLM/embed fixture'ları KALDIR.
    from pathlib import Path

    from ytcore.pipeline.api import analiz_et

    monkeypatch.delenv("YT_LLM_FIXTURE", raising=False)
    monkeypatch.delenv("YT_EMBED_FIXTURE", raising=False)
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "clean")  # ağsız TR altyazı; içerik GERÇEK model
    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="ollama-pipe", checkpoint_dir=tmp_path
    )
    assert s.dokum_segment_sayisi >= 1
    assert s.ozet_faithfulness is not None
    assert (Path(s.klasor) / "03_dokum.md").is_file()
    assert (Path(s.klasor) / "04_ozet.md").is_file()
    assert s.cloud_cagrisi_sayisi == 0  # KVKK 0-cloud gerçek model altında da korunur

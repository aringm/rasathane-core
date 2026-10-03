from __future__ import annotations

from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver
from ytcore.pipeline.graph import graph_olustur


def _calistir(tmp_output_base):
    g = graph_olustur(MemorySaver())
    return g.invoke(
        {"url": "https://youtu.be/dQw4w9WgXcQ", "konu": "genel", "asr_izin": False},
        config={"configurable": {"thread_id": "faz4-test"}},
    )


def test_pipeline_faz4_harita_ve_ses_uretir(tmp_output_base):
    # Hermetik (fixture: clean transkript + fake LLM/embed/index/memory/tts).
    son = _calistir(tmp_output_base)
    sonuc = son["sonuc"]
    assert sonuc["harita_durum"] == "uretildi"
    assert sonuc["harita_dugum_sayisi"] >= 2
    assert sonuc["ses_durum"] == "uretildi"
    klasor = son["klasor"]
    assert (Path(klasor) / "05_zihin-haritasi.html").exists()
    assert (Path(klasor) / "04_ozet.wav").exists()


def test_pipeline_faz4_0_cloud_korundu(tmp_output_base):
    # Değişmez #1: Faz 4 node'ları cloud kararını DEĞİŞTİRMEZ (local-render + KVKK-TTS).
    son = _calistir(tmp_output_base)
    assert son["sonuc"]["cloud_cagrisi_sayisi"] == 0

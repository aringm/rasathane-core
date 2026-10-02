from __future__ import annotations

from pathlib import Path

from ytcore.pipeline.api import analiz_et


def test_pipeline_02_03_04_uretir(tmp_output_base, tmp_path):
    # fixture clean = TR altyazı → çeviri atlanır, döküm+özet üretilir (fake LLM/embed).
    s = analiz_et(url="https://youtu.be/x", konu="hukuk", thread_id="f2-1", checkpoint_dir=tmp_path)
    klasor = Path(s.klasor)
    assert (klasor / "01_transcript_orijinal.md").is_file()
    assert (klasor / "03_dokum.md").is_file()
    assert (klasor / "04_ozet.md").is_file()
    assert s.ceviri_durumu == "atlandi"  # kaynak tr
    assert s.dokum_segment_sayisi >= 1
    assert s.cloud_cagrisi_sayisi == 0  # Faz 1 invariant korunur
    assert not s.stub


def test_pipeline_index_keywords_dolu(tmp_output_base, tmp_path):
    import json

    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="f2-kw", checkpoint_dir=tmp_path
    )
    idx = json.loads((Path(s.klasor) / "00_index.json").read_text(encoding="utf-8"))
    assert isinstance(idx["keywords"], list)
    assert len(idx["keywords"]) >= 1  # döküm keyword'leri index'e işlendi


def test_pipeline_faz1_invariant_korundu(tmp_output_base, tmp_path, monkeypatch):
    # PII transkript + COMPLEX → 0 cloud (Faz 1 kanıtı Faz 2 node'larıyla bozulmadı).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "pii")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    s = analiz_et(
        url="https://youtu.be/p", konu="hukuk", thread_id="f2-pii", checkpoint_dir=tmp_path
    )
    assert s.cloud_cagrisi_sayisi == 0
    assert s.pii_tespit is True


def test_pipeline_ceviri_yok_kaynak_tr(tmp_output_base, tmp_path):
    # Kaynak TR → 02_transcript_tr.md YAZILMAZ (çeviri atlandı).
    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="f2-noceviri", checkpoint_dir=tmp_path
    )
    assert not (Path(s.klasor) / "02_transcript_tr.md").exists()


def test_pipeline_altyazi_yok_dokum_ozet_yok(tmp_output_base, tmp_path, monkeypatch):
    # İçerik yoksa döküm/özet üretilmez (boş≠başarı: boş 03/04 yazma).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "altyazi_yok")
    s = analiz_et(
        url="https://youtu.be/n", konu="hukuk", thread_id="f2-yok", checkpoint_dir=tmp_path
    )
    assert s.transkript_durumu == "altyazi_yok"
    assert s.dokum_segment_sayisi == 0
    assert not (Path(s.klasor) / "03_dokum.md").exists()
    assert not (Path(s.klasor) / "04_ozet.md").exists()

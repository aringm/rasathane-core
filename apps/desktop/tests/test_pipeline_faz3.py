from __future__ import annotations

from pathlib import Path

from ytcore.pipeline.api import analiz_et


def test_pipeline_06_07_08_uretir(tmp_output_base, tmp_path):
    s = analiz_et(url="https://youtu.be/x", konu="hukuk", thread_id="f3-1", checkpoint_dir=tmp_path)
    klasor = Path(s.klasor)
    assert (klasor / "06_fact-check.md").is_file()
    assert (klasor / "07_kisisel-analiz.md").is_file()
    assert (klasor / "08_degerleme.md").is_file()
    assert s.degerleme_puani is not None and 0 <= s.degerleme_puani <= 100
    assert s.degerleme_durum == "uretildi"  # başarı yolu (review tur-3 LOW: testsizdi)
    assert s.kisisel_durum == "uretildi"
    assert s.factcheck_durum in ("uretildi", "web_yok")
    assert s.bellek_eklendi is True  # episodik bellek eklendi (gözlemlenebilirlik)
    assert s.cloud_cagrisi_sayisi == 0  # Faz 1 invariant korunur
    assert not s.stub


def test_pipeline_faz3_index_eklendi(tmp_output_base, tmp_path):
    import json

    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="f3-idx", checkpoint_dir=tmp_path
    )
    assert s.index_eklendi is True
    assert s.index.degerleme_puani is not None  # index kaydında puan dolu
    # 00_index.json'a da işlendi
    idx = json.loads((Path(s.klasor) / "00_index.json").read_text(encoding="utf-8"))
    assert idx["degerleme_puani"] is not None


def test_pipeline_faz3_altyazi_yok_zeka_atlar(tmp_output_base, tmp_path, monkeypatch):
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "altyazi_yok")
    s = analiz_et(
        url="https://youtu.be/n", konu="hukuk", thread_id="f3-yok", checkpoint_dir=tmp_path
    )
    assert not (Path(s.klasor) / "06_fact-check.md").exists()  # içerik yok → zeka atlanır
    assert not (Path(s.klasor) / "08_degerleme.md").exists()
    assert s.degerleme_puani is None
    assert s.index_eklendi is False


def test_pipeline_faz3_index_io_hata_degrade(tmp_output_base, tmp_path, monkeypatch):
    # review HIGH/MED: index.ekle I/O hatası → 06/07/08 .md KORUNUR + index_eklendi False
    # (degrade, analiz kaybolmaz, çökme yok).
    from ytcore.infra.index import FakeIndexStore

    def _patla(self, kayit, govde, vektor):
        raise RuntimeError("disk dolu")

    monkeypatch.setattr(FakeIndexStore, "ekle", _patla)
    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="f3-iohata", checkpoint_dir=tmp_path
    )
    assert s.index_eklendi is False  # I/O hatası dürüstçe yüzeyde
    assert (Path(s.klasor) / "08_degerleme.md").is_file()  # .md korundu (degrade)
    assert s.degerleme_puani is not None


def test_pipeline_faz3_index_kod_bug_reraise(tmp_output_base, tmp_path, monkeypatch):
    # review MED: index.ekle KOD_HATALARI (KeyError) → re-raise (sessizce yutulmaz).
    import pytest
    from ytcore.infra.index import FakeIndexStore

    def _bug(self, kayit, govde, vektor):
        raise KeyError("şema değişti")

    monkeypatch.setattr(FakeIndexStore, "ekle", _bug)
    with pytest.raises(KeyError):
        analiz_et(
            url="https://youtu.be/x", konu="hukuk", thread_id="f3-bug", checkpoint_dir=tmp_path
        )


def test_pipeline_faz3_bellek_hata_analiz_kaybolmaz(tmp_output_base, tmp_path, monkeypatch):
    # review tur-2 HIGH: bellek TAMAMEN best-effort — memory.ekle patlarsa (I/O VEYA kod-bug)
    # index_eklendi True kalır + 06/07/08 korunur + AnalizSonucu döner (analiz çökmez/kaybolmaz).
    from ytcore.intel.memory import FakeMemoryStore

    def _patla(self, metin, meta):
        # KOD_HATASI bile yutulmalı (index re-raise eder, bellek etmez — bilinçli asimetri).
        raise KeyError("bellek şema bug")

    monkeypatch.setattr(FakeMemoryStore, "ekle", _patla)
    s = analiz_et(
        url="https://youtu.be/x", konu="hukuk", thread_id="f3-belhata", checkpoint_dir=tmp_path
    )
    assert s.index_eklendi is True  # index bellekten bağımsız (ayrı try, başarılı)
    assert s.bellek_eklendi is False  # gözlemlenebilirlik (review tur-3 MED: sessiz-sonsuz değil)
    assert (Path(s.klasor) / "08_degerleme.md").is_file()  # analiz korundu
    assert not s.stub


def test_pipeline_faz3_pii_0_cloud_korunur(tmp_output_base, tmp_path, monkeypatch):
    # PII transkript + COMPLEX → 0 cloud (Faz 1 kanıtı Faz 3 node'larıyla bozulmadı).
    monkeypatch.setenv("YT_TRANSCRIPT_FIXTURE", "pii")
    monkeypatch.setenv("YT_FORCE_COMPLEX", "1")
    s = analiz_et(
        url="https://youtu.be/p", konu="hukuk", thread_id="f3-pii", checkpoint_dir=tmp_path
    )
    assert s.cloud_cagrisi_sayisi == 0
    assert s.pii_tespit is True

from __future__ import annotations

from ytcore.models import DegerlemeFaktorleri, IndexKaydi
from ytcore.output.degerleme_yaz import degerleme_yaz
from ytcore.output.factcheck_yaz import factcheck_yaz
from ytcore.output.kisisel_yaz import kisisel_yaz


def _kayit():
    return IndexKaydi(
        video_url="https://youtu.be/v",
        video_id="v",
        baslik="Test",
        anadil="tr",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug="v",
        analiz_tarihi="2026-06-08",
    )


def test_degerleme_yaz(tmp_path):
    fakt = DegerlemeFaktorleri(novelty=80.0, rarity=60.0, nis=70.0, recency=50.0, length=40.0)
    degerleme_yaz(tmp_path, _kayit(), 67.5, fakt)
    icerik = (tmp_path / "08_degerleme.md").read_text(encoding="utf-8")
    assert "67.5" in icerik and "Novelty" in icerik
    assert "Av. Mehmet Arın Gülüm" in icerik


def test_degerleme_yaz_recency_none(tmp_path):
    fakt = DegerlemeFaktorleri(novelty=80.0, rarity=60.0, nis=70.0, recency=None, length=40.0)
    degerleme_yaz(tmp_path, _kayit(), 67.5, fakt)
    icerik = (tmp_path / "08_degerleme.md").read_text(encoding="utf-8")
    assert "—" in icerik  # None faktör "—" gösterilir (sahte 0 değil)


def test_kisisel_yaz(tmp_path):
    kisisel_yaz(tmp_path, _kayit(), "## Hukuki Boyut\nÖnemli.")
    icerik = (tmp_path / "07_kisisel-analiz.md").read_text(encoding="utf-8")
    assert "Hukuki Boyut" in icerik and "Av. Mehmet Arın Gülüm" in icerik


def test_factcheck_yaz_web_yok(tmp_path):
    iddialar = [
        {
            "iddia": "X arttı",
            "karar": "BELİRSİZ",
            "guven": 0.0,
            "gerekce": "kaynak yok",
            "kaynaklar": [],
        }
    ]
    factcheck_yaz(tmp_path, _kayit(), iddialar, "web_yok")
    icerik = (tmp_path / "06_fact-check.md").read_text(encoding="utf-8")
    assert "BELİRSİZ" in icerik and "devre-dışı" in icerik.lower()
    assert "Av. Mehmet Arın Gülüm" in icerik


def test_factcheck_yaz_aktif_kaynak(tmp_path):
    iddialar = [
        {
            "iddia": "X arttı",
            "karar": "DESTEKLİYOR",
            "guven": 0.6,
            "gerekce": "kanıt var",
            "kaynaklar": ["https://ornek.test/1"],
        }
    ]
    factcheck_yaz(tmp_path, _kayit(), iddialar, "uretildi")
    icerik = (tmp_path / "06_fact-check.md").read_text(encoding="utf-8")
    assert "https://ornek.test/1" in icerik

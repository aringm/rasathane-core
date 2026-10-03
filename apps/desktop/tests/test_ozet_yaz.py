from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi
from ytcore.output.ozet_yaz import ozet_yaz


def _kayit() -> IndexKaydi:
    return IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="B",
        anadil="tr",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug="x",
        analiz_tarihi="2026-06-08",
    )


def test_ozet_yaz(tmp_path: Path):
    p = ozet_yaz(
        tmp_path, _kayit(), {"kisa": "TLDR.", "orta": "Orta.", "detay": "Detay."}, 0.92, "gecti"
    )
    assert p.name == "04_ozet.md"
    icerik = p.read_text(encoding="utf-8")
    assert "TLDR." in icerik and "Orta." in icerik and "Detay." in icerik
    assert "0.92" in icerik and "model değerlendirmesinde eşik sağlandı" in icerik
    assert "Model destek tahmini" in icerik
    assert "hukuki doğruluk onayı değildir" in icerik
    assert "Av. Mehmet Arın Gülüm" in icerik


def test_ozet_yaz_esik_alti_uyari(tmp_path: Path):
    p = ozet_yaz(tmp_path, _kayit(), {"kisa": "x", "orta": "y", "detay": "z"}, 0.5, "esik_alti")
    icerik = p.read_text(encoding="utf-8")
    assert "EŞİK ALTI" in icerik


def test_ozet_yaz_bos_ozet(tmp_path: Path):
    p = ozet_yaz(tmp_path, _kayit(), {"kisa": "", "orta": "", "detay": ""}, 0.0, "ozet_yok")
    icerik = p.read_text(encoding="utf-8")
    assert "_üretilemedi_" in icerik

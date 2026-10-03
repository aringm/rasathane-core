from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi
from ytcore.output.ceviri_yaz import ceviri_yaz


def _kayit() -> IndexKaydi:
    return IndexKaydi(
        video_url="https://youtu.be/x",
        video_id="x",
        baslik="B",
        anadil="en",
        kanal="K",
        konu="hukuk",
        uretici_slug="k",
        video_slug="x",
        analiz_tarihi="2026-06-08",
    )


def test_ceviri_yaz(tmp_path: Path):
    p = ceviri_yaz(tmp_path, _kayit(), "Türkçe çeviri metni.")
    assert p.name == "02_transcript_tr.md"
    icerik = p.read_text(encoding="utf-8")
    assert "Türkçe çeviri metni." in icerik
    assert "Av. Mehmet Arın Gülüm" in icerik
    assert "Türkçe Çeviri" in icerik

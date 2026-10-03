from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi
from ytcore.output.klasor import IMZA


def ceviri_yaz(klasor: Path, kayit: IndexKaydi, ceviri: str) -> Path:
    """02_transcript_tr.md (yalnız kaynak≠TR çağrılır). İmza: Av. Mehmet Arın Gülüm."""
    icerik = (
        f"# {kayit.baslik} — Türkçe Çeviri\n\n"
        f"> Kaynak: {kayit.kaynak_url or kayit.video_url}\n"
        f"> Orijinal dil: {kayit.anadil or '?'} · Analiz: {kayit.analiz_tarihi}\n\n"
        f"{ceviri.strip()}\n\n---\n_{IMZA}_\n"
    )
    p = klasor / "02_transcript_tr.md"
    p.write_text(icerik, encoding="utf-8")
    return p

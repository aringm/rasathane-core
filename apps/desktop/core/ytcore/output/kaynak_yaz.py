from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi
from ytcore.output.klasor import IMZA


def kaynak_icerigi_yaz(
    klasor: Path,
    kayit: IndexKaydi,
    metin: str,
    durum: str,
    hata: str | None = None,
) -> Path:
    """YouTube dışı normalize birincil içeriği provenance başlığıyla yaz."""
    sahip = kayit.kaynak_sahibi or kayit.kanal or "?"
    tarih = kayit.kaynak_tarihi or kayit.yayin_tarihi or "?"
    govde = metin.strip()
    if not govde:
        govde = f"_Kaynak içeriği edinilemedi: {hata or durum or 'bilinmeyen hata'}._"
    icerik = (
        f"# {kayit.baslik} — Kaynak İçeriği\n\n"
        f"> Kaynak türü: {kayit.kaynak_turu}\n"
        f"> Kanonik URL: {kayit.kaynak_url or kayit.video_url}\n"
        f"> Sahip/Yazar: {sahip} · Yayın: {tarih} · Dil: {kayit.anadil or '?'}\n"
        f"> Edinim: {durum} · Analiz: {kayit.analiz_tarihi}\n\n"
        f"{govde}\n\n---\n_{IMZA}_\n"
    )
    p = klasor / "01_kaynak-icerigi.md"
    p.write_text(icerik, encoding="utf-8")
    return p

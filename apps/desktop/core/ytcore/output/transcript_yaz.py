from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi
from ytcore.output.klasor import IMZA

# Durum -> (Edinim etiketi, boş-gövde notu). Belge KENDİSİYLE ÇELİŞMEZ: etiket ve
# gövde aynı durumdan türetilir (altyazi/asr dolu-metinle, diğerleri açık notla).
_ALTYAZI_YOK_NOT = (
    "_Bu video için altyazı bulunamadı. Yerel ASR (Whisper) ile döküm için "
    "`asr_izin=True` ile yeniden çalıştırın._"
)
_ICERIK_BOS_NOT = (
    "_Yerel ASR çalıştı ancak konuşma çıkarılamadı (video sessiz/müzik olabilir). "
    "Bu video için metinsel transkript üretilemedi._"
)


def _etiket_ve_govde(durum: str, asr_tier: str | None, hata: str | None) -> tuple[str, str]:
    if durum == "altyazi":
        return "Altyazı (yt-dlp)", ""
    if durum == "asr":
        return f"ASR ({asr_tier or 'faster-whisper'})", ""
    if durum == "icerik_bos":
        return f"ASR ({asr_tier or 'faster-whisper'}) — konuşma bulunamadı", _ICERIK_BOS_NOT
    if durum == "hata":
        not_ = f"_Video erişilemedi veya indirilemedi: {hata or 'bilinmeyen hata'}._"
        return "Erişilemedi", not_
    return "Altyazı bulunamadı", _ALTYAZI_YOK_NOT


def transcript_yaz(
    klasor: Path,
    kayit: IndexKaydi,
    metin: str,
    durum: str,
    asr_tier: str | None,
    hata: str | None = None,
) -> Path:
    """01_transcript_orijinal.md yaz (imza: Av. Mehmet Arın Gülüm).

    Gövde dolu transkript varsa metni, yoksa duruma özgü AÇIK notu içerir; Edinim
    etiketi de aynı durumdan gelir → header ile gövde tutarlı (sessiz/çelişkili çıktı yok).
    """
    etiket, bos_not = _etiket_ve_govde(durum, asr_tier, hata)
    sure = f"{kayit.sure_sn} sn" if kayit.sure_sn else "?"
    govde = metin.strip() if metin.strip() else bos_not
    icerik = (
        f"# {kayit.baslik} — Orijinal Transkript\n\n"
        f"> Kaynak: {kayit.video_url}\n"
        f"> Kanal: {kayit.kanal or '?'} · Yayın: {kayit.yayin_tarihi or '?'} · "
        f"Süre: {sure} · Dil: {kayit.anadil or '?'}\n"
        f"> Edinim: {etiket} · Analiz: {kayit.analiz_tarihi}\n\n"
        f"{govde}\n\n---\n_{IMZA}_\n"
    )
    p = klasor / "01_transcript_orijinal.md"
    p.write_text(icerik, encoding="utf-8")
    return p

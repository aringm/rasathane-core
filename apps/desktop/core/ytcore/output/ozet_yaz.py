from __future__ import annotations

from pathlib import Path

from ytcore.models import IndexKaydi
from ytcore.output.klasor import IMZA

_DURUM_NOT = {
    "gecti": "model değerlendirmesinde eşik sağlandı",
    "esik_alti": "EŞİK ALTI — düşük faithfulness, gözden geçirin",
    "yeniden_uretildi": "eşik-altı sonrası yeniden üretildi",
    "ozet_yok": "özet üretilemedi",
    "hata": "özet hatası",
}


def ozet_yaz(
    klasor: Path, kayit: IndexKaydi, ozet: dict[str, str], faithfulness: float | None, durum: str
) -> Path:
    """04_ozet.md — TL;DR/paragraf/detay + faithfulness raporu. İmza: Av. Mehmet Arın Gülüm."""
    durum_not = _DURUM_NOT.get(durum, durum or "?")
    if durum == "kaynak_alintisi":
        rapor = (
            "## Doğrudan kaynak alıntıları\n\n"
            "Model destek puanı hesaplanmadı. Edinilen resmî ana metinden alıntılar "
            "korundu; bağımsız doğrulama veya konsolide mevzuat üretimi yapılmadı.\n\n"
        )
    else:
        skor = "—" if faithfulness is None else f"{faithfulness:.2f}"
        rapor = (
            f"## Model destek tahmini (faithfulness)\n\nSkor: {skor} — {durum_not}\n\n"
            "Yerel model yalnız detaylı özeti analizde kullanılan metinle karşılaştırır. "
            "Skor, resmî kaynak doğruluğu veya hukuki doğruluk onayı değildir. "
            "Kaynak başka dilden çevrilmişse karşılaştırılan metin çeviridir.\n\n"
        )
    kapsam = ""
    if kayit.kaynak_turu == "arxiv" and kayit.kaynak_ozel.get("text_scope") == "abstract_only":
        kapsam = (
            "> Kapsam: Yalnız yayın özeti (abstract); tam makale incelenmedi.\n"
            "> Kısa/orta: Türkçe model çevirisinden doğrudan cümleler. "
            "Detay: yerel model özeti. Orijinal metin 01_kaynak-icerigi.md dosyasındadır.\n\n"
        )
    if kayit.kaynak_ozel.get("source_format") == "pdf":
        metadata = kayit.kaynak_ozel
        kapsam += (
            f"> PDF: {metadata.get('text_page_count', '?')}/{metadata.get('page_count', '?')} "
            "sayfada metin katmanı okundu.\n"
            f"> Kapsam: {metadata.get('notice', 'PDF metin katmanı; OCR yapılmadı.')}\n\n"
        )
    icerik = (
        f"# {kayit.baslik} — Özet\n\n"
        f"> Kaynak: {kayit.kaynak_url or kayit.video_url} · Dil: {kayit.anadil or '?'} · "
        f"Analiz: {kayit.analiz_tarihi}\n\n"
        f"{kapsam}"
        f"## TL;DR\n\n{ozet.get('kisa', '').strip() or '_üretilemedi_'}\n\n"
        f"## Özet\n\n{ozet.get('orta', '').strip() or '_üretilemedi_'}\n\n"
        f"## Detaylı Özet\n\n{ozet.get('detay', '').strip() or '_üretilemedi_'}\n\n"
        f"{rapor}"
        f"---\n_{IMZA}_\n"
    )
    p = klasor / "04_ozet.md"
    p.write_text(icerik, encoding="utf-8")
    return p

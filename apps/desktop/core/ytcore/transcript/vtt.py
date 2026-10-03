from __future__ import annotations

import re

_TS = re.compile(r"\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")  # cue timestamp satırı
_HTML = re.compile(r"<[^>]+>")  # <c>, <00:00:01.500>, <i> vb.
_BASLIK = re.compile(r"^(WEBVTT|Kind:|Language:|NOTE|STYLE|::cue)", re.IGNORECASE)
_INDEX = re.compile(r"^\d+$")  # SRT-tarzı cue indeksi


def temizle_vtt(icerik: str) -> str:
    """VTT/SRT altyazıyı düz metne indir: timestamp/header/HTML sil, ardışık dedup.

    Saf fonksiyon (ağ/IO yok). Ardışık tekrar dedup (auto-sub'larda aynı cümle
    iki cue'da yinelenir); HTML/inline-timestamp tag'leri strip; WEBVTT header'ları
    ve SRT cue indeksleri atlanır.
    """
    temiz: list[str] = []
    onceki: str | None = None
    for ham in icerik.splitlines():
        satir = ham.strip()
        if not satir or _TS.search(satir) or _BASLIK.match(satir) or _INDEX.match(satir):
            continue
        satir = _HTML.sub("", satir).strip()
        if satir and satir != onceki:
            temiz.append(satir)
            onceki = satir
    return " ".join(temiz)


_CUE_BAS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[.,]\d{3}\s*-->")  # cue başlangıç zamanı


def vtt_segmentler(icerik: str) -> list[dict[str, object]]:
    """VTT/SRT cue'larını zaman-damgalı segment olarak çıkar (Faz 2 kronolojik döküm
    timestamp kaynağı). [{baslangic_sn:int, metin:str}]. temizle_vtt'den BAĞIMSIZ
    (additive — Faz 1 davranışını değiştirmez); HTML/header satırları temizle_vtt ile
    aynı kurallarla strip edilir, ardışık tekrar dedup edilir."""
    segmentler: list[dict[str, object]] = []
    onceki_metin: str | None = None
    bloklar = re.split(r"\n\s*\n", icerik)
    for blok in bloklar:
        m = _CUE_BAS.search(blok)
        if not m:
            continue
        sn = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        # blok içindeki metin satırlarını temizle_vtt ile düz metne indir
        metin = temizle_vtt(blok).strip()
        if metin and metin != onceki_metin:
            segmentler.append({"baslangic_sn": sn, "metin": metin})
            onceki_metin = metin
    return segmentler

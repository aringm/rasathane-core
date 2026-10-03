from __future__ import annotations

import hashlib
import re
from typing import Any

from ytcore.models import IndexKaydi
from ytcore.text.slug import slugify

_VID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{6,})")


def url_video_id(url: str) -> str:
    """URL'den YouTube video id çıkar (hata/fallback metadata için); yoksa url-hash.

    Gerçek id çıkmazsa slug + kısa url-hash → farklı erişilemeyen URL'ler aynı
    klasöre yazıp birbirini EZMESİN (hata-yolu çakışması; re-review R5).
    """
    m = _VID.search(url or "")
    if m:
        return m.group(1)
    h = hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:8]
    taban = slugify(url or "", fallback="video")[:16]  # url or "": None'da çökme (re-review LOW)
    return f"{taban}-{h}"


def _sure(deger: Any) -> int | None:
    """duration → int; sayısal değilse ('NA', '', None, nan) None (ASLA exception).

    yt-dlp canlı/kısıtlı videolarda duration='NA' (string) döndürebilir; int('NA')
    ValueError fırlatırdı → başarılı transkripti 'hata' yapardı (re-review R1).
    """
    if deger is None:
        return None
    try:
        return int(deger)
    except (ValueError, TypeError):
        return None


def _tarih(yyyymmdd: str | None) -> str | None:
    """yt-dlp upload_date (YYYYMMDD) → YYYY-MM-DD; geçersizse None."""
    if not yyyymmdd or len(yyyymmdd) != 8 or not yyyymmdd.isdigit():
        return None
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def info_to_index(info: dict[str, Any], konu: str, analiz_tarihi: str) -> IndexKaydi:
    """yt-dlp info dict → IndexKaydi (gerçek metadata; faz0_stub=False)."""
    # str() coercion: yt-dlp anomali (non-str title/channel) slugify.translate()'i
    # try DIŞINDA çökertmesin (re-review LOW; savunmacı sınır).
    kanal = str(info.get("channel") or info.get("uploader") or "")
    baslik = str(info.get("title") or "(başlık yok)")
    return IndexKaydi(
        video_url=info.get("webpage_url") or info.get("original_url") or "",
        video_id=info.get("id") or "video",
        baslik=baslik,
        anadil=(info.get("language") or ""),
        kanal=kanal,
        yayin_tarihi=_tarih(info.get("upload_date")),
        sure_sn=_sure(info.get("duration")),
        konu=konu,
        uretici_slug=slugify(kanal, fallback="kanal"),
        video_slug=slugify(baslik, fallback=(info.get("id") or "video"))[:48],
        analiz_tarihi=analiz_tarihi,
        keywords=[],
        faz0_stub=False,
        kaynak_turu="youtube",
        kaynak_url=info.get("webpage_url") or info.get("original_url") or "",
        kaynak_id=info.get("id") or "video",
        kaynak_sahibi=kanal,
        kaynak_tarihi=_tarih(info.get("upload_date")),
    )

from __future__ import annotations

import re
import unicodedata

from ytcore.content.llm import LLMClient
from ytcore.content.segment import cumlelere_bol, semantic_chunk
from ytcore.infra.embedding import EmbeddingProvider

__all__ = ["semantic_chunk", "ozetle"]

_MAP_SISTEM = (
    "Bu transkript bölümünü Türkçe olarak özetle. Anahtar noktaları koru, yorum katma. "
    "Yalnız özet metnini döndür; 'İşte özet' gibi giriş cümlesi veya başlık ekleme."
)
_REDUCE_DETAY = (
    "Aşağıdaki bölüm özetlerini tek tutarlı, akıcı Türkçe detaylı özette birleştir. "
    "Bölümlerdeki anahtar noktaları koru. Yalnız özet metnini döndür; giriş cümlesi ekleme."
)
_REDUCE_ORTA = (
    "Bu metni akıcı, tutarlı tek paragraflık Türkçe özete dönüştür. "
    "Yalnız özeti döndür; giriş cümlesi ekleme."
)
_REDUCE_KISA = "Bu metni tek cümlelik Türkçe TL;DR özetine indir. Yalnız o cümleyi döndür."


def abstract_cumleleri(metin: str) -> dict[str, str]:
    """İlk üç tam cümle; belirsiz kısaltma sınırında bütün abstract/çeviri korunur."""
    boundaries = list(re.finditer(r"(?<=[.!?])\s+(?=[A-ZÇĞİÖŞÜ])", metin))
    quote_or_bracket = any(
        char in '"<>' or unicodedata.category(char) in {"Ps", "Pe", "Pi", "Pf"} for char in metin
    ) or bool(re.search(r"(?:^|\s)'(?=\S)", metin))
    ambiguous = quote_or_bracket or any(
        re.search(
            r"(?:^|\s)(?:[A-Za-zÇĞİÖŞÜçğıöşü]{1,4}|(?:[A-Za-z]\.)+[A-Za-z])\.$"
            r"|\d\.$|[.!?]{2,}$",
            metin[: boundary.start()],
        )
        for boundary in boundaries
    )
    kisa = metin[: boundaries[2].start()] if len(boundaries) >= 3 and not ambiguous else metin
    return {"kisa": kisa.strip(), "orta": metin.strip()}


def ozetle(
    metin: str,
    llm: LLMClient,
    embed: EmbeddingProvider,
    *,
    map_model: str | None = None,
    reduce_model: str | None = None,
    hedef_kar: int = 4000,
    kaynak_cumleleri: bool = False,
) -> dict[str, str]:
    """Semantic-chunk map-reduce özet. Çıktı: kisa(TL;DR)/orta(paragraf)/detay.

    Boş girdi → boş sonuç (sessiz). Boş model çıktısı → ValueError (boş≠başarı — Faz 1 dersi:
    boş özet sessiz 'başarı' verme).
    """
    bos = {"kisa": "", "orta": "", "detay": ""}
    if not metin.strip():
        return bos
    cumleler = cumlelere_bol(metin)
    parcalar = semantic_chunk(cumleler, embed, hedef_kar=hedef_kar)
    # MAP: her parça bağımsız özet
    map_ozetler = [llm.uret(_MAP_SISTEM, p, model=map_model).strip() for p in parcalar]
    map_ozetler = [m for m in map_ozetler if m]
    if not map_ozetler:
        raise ValueError("Özet map aşaması boş döndü (boş≠başarı)")
    birlesik = "\n".join(map_ozetler)
    # REDUCE: detay → orta → kısa (hiyerarşik)
    detay = llm.uret(_REDUCE_DETAY, birlesik, model=reduce_model).strip()
    if not detay:
        raise ValueError("Özet reduce (detay) boş döndü (boş≠başarı)")
    if kaynak_cumleleri:
        return {**abstract_cumleleri(metin), "detay": detay}
    # orta/kısa boş dönerse detay'dan TÜRET (boş katman + 'gecti' çelişkisi olmasın — review
    # MED: 3 özet katmanından 2'si sessizce boş kalip faithfulness 'gecti' ile çelişmesin).
    orta = llm.uret(_REDUCE_ORTA, detay, model=reduce_model).strip() or detay
    kisa = llm.uret(_REDUCE_KISA, orta, model=reduce_model).strip()
    if not kisa:
        orta_cumleler = cumlelere_bol(orta)
        kisa = orta_cumleler[0] if orta_cumleler else orta
    return {"kisa": kisa, "orta": orta, "detay": detay}

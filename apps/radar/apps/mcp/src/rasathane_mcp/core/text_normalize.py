"""Phase 15-iii: text normalization helpers.

Akış (canlı feed) görünümünde başlıkların büyük-küçük harf uyumu
karışıktı: bazı RSS kaynakları ALL CAPS başlık verirken bazıları
Title Case veya sentence case kullanıyor. ``normalize_title_tr``
heuristic ile ALL CAPS'i sentence case'e çevirir; geri kalanları
olduğu gibi bırakır.

Türkçe büyük-küçük harf çiftleri: ``İ↔i``, ``I↔ı``. Python'un
varsayılan ``.lower()`` Windows locale'a göre değişebileceği
için kendi mapping'imizi kullanıyoruz (idempotent + cross-platform).
"""

from __future__ import annotations

# Türkçe upper → lower haritalaması. Diğer karakterler casefold'a düşer.
_TR_UPPER_TO_LOWER = {
    "İ": "i",
    "I": "ı",
    "Ş": "ş",
    "Ğ": "ğ",
    "Ü": "ü",
    "Ö": "ö",
    "Ç": "ç",
    "Â": "â",
    "Î": "î",
    "Û": "û",
}
_TR_LOWER_TO_UPPER = {v: k for k, v in _TR_UPPER_TO_LOWER.items()}

# ALL CAPS kabul edilmek için harflerin en az %80'i upper olmalı.
# Düşük eşikler "Cumhurbaşkanlığı KVKK Kararı" gibi mixed-case başlıkları
# yanlış normalize ederdi.
_ALLCAPS_THRESHOLD = 0.80
# Kısa başlıkları (≤2 kelime) hiç normalize etme — büyük olasılıkla
# akronim ("KVKK", "AYM TBMM") veya tek kelime markası.
_MIN_WORDS_FOR_NORMALIZE = 3


def tr_lower(s: str) -> str:
    """Türkçe-aware lowercase. Stdlib ``str.lower()`` Windows locale'da
    "I" → "i" yapabilir (yanlış); biz "I" → "ı" zorunlu kılıyoruz.
    """
    return "".join(_TR_UPPER_TO_LOWER.get(c, c.lower()) for c in s)


def tr_upper_first(s: str) -> str:
    """İlk karakteri Türkçe upper, kalanı dokunulmaz."""
    if not s:
        return s
    first = _TR_LOWER_TO_UPPER.get(s[0], s[0].upper())
    return first + s[1:]


def is_mostly_uppercase(s: str, *, threshold: float = _ALLCAPS_THRESHOLD) -> bool:
    """Sayılar/sembol/boşluk hariç harflerin %X'i upper mı?

    Boş veya harfsiz string ``False`` (normalize etme).
    """
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return (upper / len(letters)) >= threshold


def normalize_title_tr(title: str) -> str:
    """Bir başlığı UI gösterimine uygun forma getirir.

    Kurallar:
    - None / boş → olduğu gibi
    - Kelime sayısı < 3 → dokunma (akronim/marka olabilir)
    - %80+ upper değilse → dokunma (zaten karma case)
    - Aksi → tüm string'i tr_lower + ilk karakteri tr_upper_first

    Bu normalize **idempotent** — ikinci çağrı aynı sonucu döndürür.
    Original ham ``title`` DB'de kalır, ``title_display`` UI için.
    """
    if not title:
        return title
    stripped = title.strip()
    if not stripped:
        return stripped
    words = stripped.split()
    if len(words) < _MIN_WORDS_FOR_NORMALIZE:
        return stripped
    if not is_mostly_uppercase(stripped):
        return stripped
    lowered = tr_lower(stripped)
    return tr_upper_first(lowered)

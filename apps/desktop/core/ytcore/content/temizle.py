"""Faz 6 (#1): YouTube transkript temizliği — hibrit (regex ön-temizlik + LLM bağlamsal).

Bunun bir YouTube videosu olduğunu BİLEREK temizler: ses etiketleri, oto-altyazı tekrarları,
reklam/sponsor okumaları, 'abone ol/beğen/zili aç' kanal çağrıları, dolgu sesleri çıkarılır;
cümleler bütünlenir. İÇERİK KORUNUR (özetleme/çeviri YOK). Çıktı orijinal dildedir; çeviri
sonraki node'da yapılır. Torch-free: LLM Ollama-HTTP (qwen2.5:14b reuse — yeni model yok, #2).
"""

from __future__ import annotations

import re

from ytcore.content.llm import LLMClient

# [Music] [Müzik] [Applause] [Alkış] [♪] (♪♪) gibi köşeli/parantez ses/sahne etiketleri.
_SES_ETIKET = re.compile(r"[\[(][^\])]{0,40}[\])]")
# Ardışık tekrar eden kelime (oto-altyazı kekemesi: "the the the" / "evet evet evet").
_TEKRAR = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE | re.UNICODE)
_COK_BOSLUK = re.compile(r"[ \t]{2,}")
_COK_SATIR = re.compile(r"\n{3,}")

_SISTEM = (
    "Bu bir YouTube video transkriptidir. Görevin bu transkripti TEMİZLEMEK. Şunları ÇIKAR: "
    "reklam ve sponsor okumaları; 'abone ol / beğen / zili aç / yorum yap / kanalıma hoş geldiniz' "
    "türü kanal çağrıları; anlamsız tekrarlar; dolgu sesleri (ee, ıı, yani yani, hani). "
    "Bölük cümleleri bütünle ve noktalama ekle. KONUŞMANIN İÇERİĞİNİ AYNEN KORU. "
    "ÖZETLEME, ÇEVİRME, YORUM/BAŞLIK EKLEME. Metni hangi dildeyse O DİLDE döndür. "
    "Yalnızca temizlenmiş transkript metnini yaz, başka hiçbir şey yazma."
)


def _regex_on_temizlik(metin: str) -> str:
    metin = _SES_ETIKET.sub(" ", metin)
    metin = _TEKRAR.sub(r"\1", metin)
    metin = _COK_BOSLUK.sub(" ", metin)
    metin = _COK_SATIR.sub("\n\n", metin)
    return metin.strip()


def temizle_kaynak(metin: str) -> str:
    """Yazılı kaynaklarda anlamı değiştirmeden yalnız whitespace'i normalize et.

    GitHub README, arXiv özeti, Reddit gönderisi, Hugging Face card ve web makalesine
    YouTube'a özgü sponsor/dolgu prompt'u uygulanmaz. Adapter zaten ana içeriği seçer.
    """
    metin = _COK_BOSLUK.sub(" ", metin.replace("\r\n", "\n").replace("\r", "\n"))
    return _COK_SATIR.sub("\n\n", metin).strip()


def temizle_youtube(metin: str, llm: LLMClient, *, model: str | None = None) -> str:
    """Hibrit temizlik: regex ön-temizlik → LLM bağlamsal temizlik.

    Boş/çok kısa girdi → yalnız regex (LLM'e gönderme). LLM aşırı agresif kısaltırsa
    (boş≠başarı) regex çıktısını koru — temizlik içerik kaybına dönüşmesin.
    """
    on = _regex_on_temizlik(metin)
    if len(on) < 200:  # çok kısa → bağlamsal temizliğe değmez
        return on
    cikti = llm.uret(_SISTEM, on, model=model).strip()
    # LLM çıktısı makul uzunlukta mı? Aşırı kısaysa (özetlemiş/koparmış) → regex çıktısını koru.
    return cikti if len(cikti) >= len(on) * 0.4 else on

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Karmasiklik(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
    REASONING = "reasoning"


class Hedef(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass
class Yonlendirme:
    hedef: Hedef
    gerekce: str


def yonlendir(
    karmasiklik: Karmasiklik, pii_var: bool, cloud_erisilebilir: bool = True
) -> Yonlendirme:
    """Complexity router + HARD-OVERRIDE.

    HARD-OVERRIDE kuraldan ÖNCE: PII/KVKK -> HER ZAMAN local (fail-closed).
    """
    if pii_var:
        return Yonlendirme(Hedef.LOCAL, "PII tespit edildi: KVKK fail-closed")
    if not cloud_erisilebilir:
        return Yonlendirme(Hedef.LOCAL, "cloud erişilemez: graceful degrade")
    if karmasiklik in (Karmasiklik.COMPLEX, Karmasiklik.REASONING):
        return Yonlendirme(Hedef.CLOUD, "PII-temiz karmaşık görev")
    return Yonlendirme(Hedef.LOCAL, "basit/orta görev local")


# Muhakeme işaretleri: TR hukuki/analitik görev sinyalleri. Eşikler ARAŞTIRMA-DEFAULT
# (A11: heuristik <1ms); TR held-out korpus gelince kalibre edilir (değişmez #3 —
# KİLİTLİ DEĞİL). Muhafazakâr bias: şüphede LOCAL yönü (yanlış-COMPLEX = gereksiz cloud
# egress riski; yanlış-SIMPLE = yalnız kalite kaybı).
_MUHAKEME = (
    "neden",
    "karşılaştır",
    "değerlendir",
    "analiz",
    "çelişki",
    "kanıtla",
    "gerekçe",
    "strateji",
    "adım adım",
    "eleştir",
    "yorumla",
)
_REASONING = ("ispat", "teorem", "matematiksel kanıt", "algoritmik")


def _katlanmis(metin: str) -> str:
    # Güvenli TR katlama (Faz 2/4 dersi + review tur-1): 'İ'.lower() = 'i' + U+0307
    # (combining dot) → dot sökülür; 'I'.lower() = ASCII 'i' ama TR'de 'ı' beklenir →
    # ı/i tek forma indirgenir (ı→i). İşaretler de AYNI katlamadan geçirilir (simetri).
    return metin.lower().replace("̇", "").replace("ı", "i")


def siniflandir(metin: str, konu: str = "genel") -> Karmasiklik:
    """Heuristik complexity sınıflandırma (saf-python, <1ms — A11 doğrulanmış yaklaşım).

    Eşikler env ile override: YT_COMPLEXITY_ESIK (muhakeme-işaret sayısı, default 3),
    YT_COMPLEXITY_ORTA_SOZCUK (default 800). TR korpus gelince kalibre (master-merge moat).
    """
    import os

    esik = int(os.environ.get("YT_COMPLEXITY_ESIK", "3"))
    orta_sozcuk = int(os.environ.get("YT_COMPLEXITY_ORTA_SOZCUK", "800"))
    k = _katlanmis(metin)
    # İşaretler de katlanır (review tur-1: 'karşılaştır' içindeki 'ı' ile metnin
    # 'KARŞILAŞTIR'.lower()='karşilaştir' formu ancak iki taraf da katlanınca eşleşir).
    puan = sum(1 for m in _MUHAKEME if _katlanmis(m) in k)
    if puan >= esik and any(_katlanmis(m) in k for m in _REASONING):
        return Karmasiklik.REASONING
    if puan >= esik:
        return Karmasiklik.COMPLEX
    if len(metin.split()) > orta_sozcuk:
        return Karmasiklik.MEDIUM
    return Karmasiklik.SIMPLE

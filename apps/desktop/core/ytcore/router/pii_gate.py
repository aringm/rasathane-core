from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Normalize edilmiş (ayraçsız) metin üzerinde:
_RAKAM11 = re.compile(r"(?<!\d)\d{11,}(?!\d)")  # 11+ haneli blok: TCKN/uzun-numara şüphesi
_GSM = re.compile(r"(?:\+?90)?0?5\d{9}(?!\d)")  # 10-haneli GSM (5xx...)
_IBAN = re.compile(r"TR\d{24}", re.IGNORECASE)  # TR + 24 hane

# Ayraçlar (boşluk, nokta, tire, parantez, slash) — gerçek PII bunlarla yazılır:
# "123 456 789 50", "0(532) 123 45 67", "532.123.45.67", "TR07.0001..."
_AYRAC = re.compile(r"[\s.\-()/]")
_BOSLUK = re.compile(r"\s+")

# --- Faz 1: hukuki-bağlam PII (NER'siz, İSABETLİ desenler, fail-closed) ---
# Pattern-tabanlı gate sayı/email/IBAN/kimlik-ifadesi/adres-bağlamı yakalar.
# ⚠️ AD-SOYAD tespiti BİLİNÇLİ olarak Faz 2'ye ertelendi: regex "rol + Büyükharf-ad"
# kişi-adı ile kurum/yer adını (Yargıtay, Anayasa Mahkemesi, Bakırköy Adliyesi) AYIRT
# EDEMEZ → ya fail-OPEN (case kaçar) ya over-flag (hukuk içeriğinde router'ı kapatır).
# Gerçek çözüm istatistiksel NER (Faz 2 BLOKER: gerçek cloud client gelmeden ÖNCE).
# Faz 1 güvenli çünkü cloud yolu no-op stub (literal sızıntı yok). Kanonik "müvekkil
# <ad> ... <adres>'te oturuyor" vakası adres-bağlamı deseniyle yakalanır.
_KIMLIK_BAGLAM = re.compile(
    r"kimlik\s*(numara|no\b)|adına kayıtlı|adina kayitli|nüfus|nufus|"
    r"doğum tarihi|dogum tarihi|t\.?c\.?\s*kimlik|pasaport\s*(numara|no)",
    re.IGNORECASE | re.UNICODE,
)
# Adres = adres-tipi sözcük VE ikamet-fiili birlikte (tek başına "X Caddesi" flag'lemez)
_ADRES_TIP = re.compile(
    r"cadde|sokağ|sokak|\bsok\b|\bcad\b|mahalle|\bmah\b|bulvar|apartman|"
    r"\bdaire\b|\bblok\b|site(si)?\b",
    re.IGNORECASE | re.UNICODE,
)
_IKAMET = re.compile(
    r"otur|ikamet|mukim|ikametgah|adres(in|im|i)|evinde",
    re.IGNORECASE | re.UNICODE,
)


@dataclass
class PIISonuc:
    var: bool
    turler: list[str] = field(default_factory=list)


def _sadelestir(metin: str) -> str:
    """Ayraçları sök — gerçek PII (boşluklu/noktalı/parantezli) fail-OPEN kaçmasın."""
    return _AYRAC.sub("", metin)


def pii_iceriyor_mu(metin: str) -> PIISonuc:
    """KVKK fail-closed PII tespiti (deny-by-default).

    Eşleştirme ayraçsız (normalize) kopyada yapılır; böylece "123 456 789 50",
    "0(532) 123 45 67", "532.123.45.67", "TR07.0001..." gibi yaygın yazımlar da
    yakalanır. 11+ haneli her blok şüpheli sayılır (gerçek TCKN doğrulaması Faz 2).
    Ayrıca hukuki-bağlam adlandırılmış-PII (ad-soyad/adres/kimlik ifadesi) dar
    desenlerle yakalanır. Amaç: yanlış-negatifi minimize et — şüpheli içerik
    cloud'a DEĞİL local'e düşsün.
    """
    turler: list[str] = []
    norm = _sadelestir(metin)
    bosluksuz = _BOSLUK.sub("", metin)
    # E-posta: orijinalde VE boşluksuz kopyada ara ("ahmet @ firma.com" fail-OPEN kaçmasın)
    if _EMAIL.search(metin) or _EMAIL.search(bosluksuz):
        turler.append("email")
    if _IBAN.search(norm):
        turler.append("iban")
    if _RAKAM11.search(norm):
        turler.append("tckn")
    if _GSM.search(norm):
        turler.append("telefon")
    if _KIMLIK_BAGLAM.search(metin):
        turler.append("kimlik")
    if _ADRES_TIP.search(metin) and _IKAMET.search(metin):
        turler.append("adres")
    return PIISonuc(var=len(turler) > 0, turler=turler)

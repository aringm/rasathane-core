from __future__ import annotations

import re

from ytcore.router.pii_gate import pii_iceriyor_mu

# Maskeleme için literal eşleşme (pii_gate tespit-için normalize eder; burada
# olgusal çekirdeği koruyarak yerinde maskeleriz). Sıra önemli: email/IBAN/TCKN/telefon.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+\s*@\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IBAN = re.compile(r"\bTR\d{2}[\s]?(?:\d{4}[\s]?){5}\d{2}\b", re.IGNORECASE)
# 11+ hane (pii_gate _RAKAM11 ile hizalı — 12+ haneli hesap/kimlik no da maskelenir).
_TCKN = re.compile(r"(?<!\d)\d{11,}(?!\d)")
_TELEFON = re.compile(r"(?:\+90|0)?[\s.\-(]*5\d{2}[\s.\-)]*\d{3}[\s.\-]*\d{2}[\s.\-]*\d{2}")
_MASKE = "[gizli]"


def anonimlestir(metin: str) -> tuple[str, bool]:
    """Olgusal çekirdeği koruyarak PII'yi maskele (web sorgusuna PII GİTMEZ — KVKK).

    pii_gate'in tespit ettiği desenleri (email/IBAN/TCKN/telefon) maskeler. İSİM NER
    Faz 5'e ertelendi (Faz 1 dersi: regex isim-tespiti fail-open/over-flag) — burada
    yalnız literal-desen. Döndürür: (maskelenmiş_metin, değişti_mi).
    """
    orijinal = metin
    for desen in (_EMAIL, _IBAN, _TCKN, _TELEFON):
        metin = desen.sub(_MASKE, metin)
    return metin, (metin != orijinal)


def pii_var_mi(metin: str) -> bool:
    """Sorgu gönderilmeden ÖNCE son kontrol: hâlâ PII içeriyor mu (deny-by-default)."""
    return pii_iceriyor_mu(metin).var


def egress_pii_var_mi(metin: str) -> bool:
    """Web egress deny-by-default kontrolü — KVKK FAIL-CLOSED (değişmez #1).

    pii_gate'in TESPİT ETTİĞİ TÜM PII türlerini (email/iban/tckn/telefon/adres + kimlik-bağlam)
    bloklar: pii_gate'in gördüğü PII'yi içeren hiçbir iddia üçüncü-taraf web servisine GİTMEZ.

    ⚠️ KAPSAM (review tur-5 LOW): bu garanti pii_gate'in YAKALADIĞI PII ile sınırlı. pii_gate'in
    kaçırdığı sınıflar (çıplak ad-soyad, adres-tipi-tek-başına ikamet-fiilsiz, plaka, at/dot-
    gizlenmiş email) fail-OPEN sızar — bunlar ad-soyad NER + genişletilmiş desenle Faz 5'e erteli
    (Faz 1/2 dersi: regex isim-tespiti fail-open/over-flag; pii_gate bilinçli pattern+keyword).

    ⚠️ BİLİNÇLİ FAIL-CLOSED KARARI (review tur-2/3/4): 'kimlik' türü hem meşru demografik
    ('Türkiye nüfusu 85 milyon') hem GERÇEK kişisel-veri belge bağlamını ('nüfus cüzdanı',
    'nüfus kayıt örneği', 'nüfusa kayıtlı Ahmet Yılmaz', 'doğum tarihi', 'T.C. kimlik no',
    'pasaport no') aynı kelimelerle (_KIMLIK_BAGLAM) yakalar. NER olmadan (Faz 5) ikisi kesin
    AYRILAMAZ — 'kimlik'i egress'e açma denemeleri (tur-2/3) tekrar tekrar gerçek-PII sızıntısı
    (HIGH) üretti. Fail-closed bias: ŞÜPHEDE BLOKLA. Bedel: birkaç demografik iddia web-fact-
    check'ten düşer (MED işlevsellik); kazanç: pii_gate'in gördüğü kimlik-bağlam sızmaz.
    Faz 5'te ad-soyad NER + demografik/belge ayrımı bu fail-closed'u gevşetebilir."""
    return pii_iceriyor_mu(metin).var

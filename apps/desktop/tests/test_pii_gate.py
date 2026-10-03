from __future__ import annotations

from ytcore.router.pii_gate import pii_iceriyor_mu


def test_tc_kimlik():
    r = pii_iceriyor_mu("Müvekkilim 12345678950 numaralı kişi")
    assert r.var is True and "tckn" in r.turler


def test_email_ve_telefon():
    assert pii_iceriyor_mu("a@b.com").var is True
    assert pii_iceriyor_mu("0532 123 45 67").var is True
    assert pii_iceriyor_mu("+90 532 1234567").var is True


def test_iban():
    assert pii_iceriyor_mu("TR07 0001 5001 5800 7303 1089 61").var is True


def test_temiz_metin():
    r = pii_iceriyor_mu("Bu bir yapay zeka semineri özetidir.")
    assert r.var is False and r.turler == []


def test_deny_by_default_supheli():
    # 11 haneli ama geçersiz TC -> yine de şüpheli sayılır (fail-closed)
    r = pii_iceriyor_mu("kimlik 00000000000")
    assert r.var is True


def test_ayracli_tckn_kacmamali():
    # Adversarial review: boşluklu/gömülü TCKN fail-OPEN kaçıyordu
    assert pii_iceriyor_mu("123 456 789 50").var is True
    assert pii_iceriyor_mu("kimlik: 1234567895012345").var is True  # 11+ blok


def test_ayracli_telefon_kacmamali():
    # parantezli / noktalı telefon
    assert pii_iceriyor_mu("0(532) 123 45 67").var is True
    assert pii_iceriyor_mu("532.123.45.67").var is True


def test_noktali_iban_kacmamali():
    assert pii_iceriyor_mu("TR07.0001.5001.5800.7303.1089.61").var is True


def test_masum_sayilar_asiri_flaglanmamali():
    # Sınır: harfle ayrılmış sayılar birleşmez; kısa rakam blokları PII değil.
    # (fail-closed YÖNÜNDE over-flag kabul; ama harf-ayraçlı/kısa sayılar temiz kalmalı)
    assert pii_iceriyor_mu("ürün 12345 ve 678901 stokta").var is False
    assert pii_iceriyor_mu("tarih 07.06.2026 toplantı").var is False
    assert pii_iceriyor_mu("yıllar 2020-2026 arası").var is False


def test_transkriptte_konusulan_tckn_yakalanir():
    # Faz 1 değişmez #1: PII artık GERÇEK transkript metnine uygulanır.
    metin = "Müvekkilin kimlik numarası 12345678950 olarak kayıtlı."
    assert pii_iceriyor_mu(metin).var is True


def test_temiz_transkript_pii_yok():
    assert pii_iceriyor_mu("Sözleşme hukuku irade serbestisi üzerinedir.").var is False


# --- Adversarial review HIGH/MED: adlandırılmış-PII + boşluklu email (fail-OPEN) ---


def test_adres_baglami_iceren_transkript_yakalanir():
    # Review HIGH: kanonik avukatlık vakası adres-bağlamı (cadde + ikamet) ile yakalanır.
    metin = (
        "Müvekkilim Ahmet Yılmaz, eşi Ayşe Hanım ile birlikte Kadıköy "
        "Bağdat Caddesinde oturuyor ve bu davada taraf."
    )
    r = pii_iceriyor_mu(metin)
    assert r.var is True and "adres" in r.turler


def test_kurum_yer_adi_asiri_flaglanmamali():
    # Re-review R3: "rol + Büyükharf-kurum" YANLIŞ 'isim' PII sayılmamalı (router'ı
    # hukuk içeriğinde kapatırdı). İsim-tespiti regex'le YAPILMAZ (Faz 2 NER).
    assert pii_iceriyor_mu("davacı Yargıtay kararına dayandı.").var is False
    assert pii_iceriyor_mu("sanık Bakırköy Adliyesinde yargılandı.").var is False
    assert pii_iceriyor_mu("müvekkil Anayasa Mahkemesine başvurdu.").var is False
    assert pii_iceriyor_mu("mağdur Avrupa İnsan Hakları Mahkemesine gitti.").var is False


def test_kimlik_ifadesi_baglami():
    assert pii_iceriyor_mu("Adına kayıtlı taşınmaz var.").var is True
    assert pii_iceriyor_mu("Doğum tarihi 1980 olarak geçiyor.").var is True


def test_bosluklu_email_kacmamali():
    # Review MED: auto-caption/STT '@' etrafına boşluk koyar → fail-OPEN olmamalı
    assert pii_iceriyor_mu("iletişim ahmet @ firma.com").var is True
    assert pii_iceriyor_mu("ahmet@ gmail.com").var is True


def test_temiz_fixture_metni_temiz_kalir():
    # KRİTİK regresyon: clean fixture metni PII-temiz kalmalı (cloud-kontrast testi buna
    # dayanır; yeni adlandırılmış-PII desenleri normal hukuk içeriğini flag'lememeli).
    clean = (
        "Bugün sözleşme hukukunun temel ilkelerini konuşacağız. "
        "İrade serbestisi modern borçlar hukukunun çekirdeğidir."
    )
    assert pii_iceriyor_mu(clean).var is False


def test_genel_cografi_icerik_asiri_flaglanmamali():
    # Sokak adı TEK BAŞINA flag'lememeli (router'ı bozmasın) — ikamet-fiili de gerekir
    assert pii_iceriyor_mu("İstiklal Caddesinde yürüyüş yaptık.").var is False
    assert pii_iceriyor_mu("Bağdat Caddesi İstanbul'un önemli bir aksıdır.").var is False

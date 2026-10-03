from __future__ import annotations

from ytcore.intel.anonim import anonimlestir, egress_pii_var_mi, pii_var_mi


def test_anonim_email_maskeler():
    s, degisti = anonimlestir("Sözleşme ahmet@example.com adresine gönderildi.")
    assert "ahmet@example.com" not in s
    assert degisti is True
    assert "Sözleşme" in s and "gönderildi" in s  # olgusal çekirdek korunur


def test_anonim_tckn_telefon_maskeler():
    s, _ = anonimlestir("Müvekkil 12345678901 ve 0532 123 45 67 numaralı.")
    assert "12345678901" not in s
    assert "0532 123 45 67" not in s  # telefon maskelendi


def test_anonim_temiz_metin_degismez():
    s, degisti = anonimlestir("Enflasyon 2025'te yüzde 40 arttı.")
    assert degisti is False
    assert s == "Enflasyon 2025'te yüzde 40 arttı."


def test_anonim_iban_maskeler():
    s, degisti = anonimlestir("Ödeme TR330006100519786457841326 hesabına yapıldı.")
    assert "TR330006100519786457841326" not in s
    assert degisti is True


def test_pii_var_mi():
    assert pii_var_mi("ahmet@example.com") is True
    assert pii_var_mi("enflasyon arttı") is False


def test_egress_pii_var_mi_gercek_sizinti_bloklar():
    # Gerçek sızıntı türleri → egress blok.
    assert egress_pii_var_mi("ahmet@example.com yazdı") is True  # email
    assert egress_pii_var_mi("Bakırköy Caddesinde oturuyor") is True  # adres
    assert egress_pii_var_mi("0532 111 22 33 aradı") is True  # telefon


def test_egress_pii_var_mi_kimlik_fail_closed():
    # review tur-4: KVKK FAIL-CLOSED (değişmez #1) — TÜM kimlik-bağlam egress'te BLOKLANIR.
    # kimlik-belgesi (gerçek PII) + demografik 'nüfus' (NER'siz ayrılamaz) → şüphede blokla.
    assert egress_pii_var_mi("doğum tarihi 1 Ocak 1980") is True
    assert egress_pii_var_mi("T.C. kimlik numarası okundu") is True
    assert egress_pii_var_mi("pasaport numarası eklendi") is True
    assert egress_pii_var_mi("nüfus cüzdanı fotokopisi dosyada") is True  # belge bağlamı
    assert egress_pii_var_mi("Ahmet Yılmaz nüfusa kayıtlı") is True  # belge bağlamı
    # Demografik 'nüfus' da BİLİNÇLİ bloklanır (fail-closed bedeli; NER Faz 5 gevşetebilir).
    assert egress_pii_var_mi("Türkiye nüfusu 85 milyona ulaştı") is True


def test_egress_pii_var_mi_temiz_izin():
    # PII içermeyen olgusal iddia → egress İZİN (fail-closed yalnız PII'de devreye girer).
    assert egress_pii_var_mi("enflasyon yüzde 40 arttı") is False
    assert egress_pii_var_mi("2025 yılında faiz indirildi") is False

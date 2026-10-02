from __future__ import annotations

import re

from ytcore.intel.anonim import egress_pii_var_mi
from ytcore.intel.factcheck import fact_check
from ytcore.intel.websearch import SerperSearch


class _SatirLLM:
    """Her cümleyi AYRI iddia (satır) olarak döndüren sahte claim-decomposer.

    FakeLLM tüm girdiyi tek-satır echo eder → iddialari_cikar tek-iddiaya collapse olur
    (tüm cümleler birleşik PII'li tek-iddia → guard hepsini bloklar → yakalanan boş → oracle
    VACUOUS, review tur-2 MED). Bu LLM cümle-başına-iddia üretir → temiz/PII karışımı test edilir.
    """

    def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
        return "\n".join(c.strip() for c in re.split(r"(?<=[.!?])\s+", kullanici) if c.strip())


def _spy(yakalanan):
    def sahte_ara_durumlu(self, sorgu, n=5):
        yakalanan.append(sorgu)
        return [], "aktif"  # anahtar varmış gibi (egress simülasyonu)

    return sahte_ara_durumlu


def test_web_sorgusunda_egress_pii_yok(monkeypatch):
    """KVKK GENEL enforcement (non-vacuous): web'e GİDEN her sorguda gerçek sızıntı-PII'si yok.

    Karışık iddialar (satır-bölen LLM): temiz/maskelenmiş GÖNDERİLİR, adres/tckn BLOKLANIR.
    Oracle = egress_pii_var_mi (router over-flag değil). Guard silinse KIRMIZI; oracle döngüsü
    BOŞ değil (temiz iddialar gerçekten gönderilir — review tur-2 MED vacuous-fix).
    """
    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    metin = (
        "Enflasyon 2025 yılında yüzde 40 arttı. "  # temiz → gönderilmeli
        "Müvekkil ahmet@example.com adresinden yazdı. "  # email → maskelenip gönderilir
        "Müvekkil Bakırköy Atatürk Caddesinde oturuyor. "  # adres → BLOKLANIR
        "Hesap numarası 12345678901 kapatıldı."  # tckn → maskelenip gönderilir
    )
    fact_check(metin, _SatirLLM(), web)

    assert yakalanan, "temiz/maskelenmiş iddialar gönderilmeli (oracle boş değil)"
    # GÖNDERİLEN hiçbir sorguda gerçek sızıntı-PII'si olmamalı (email/tckn/telefon/adres).
    for sorgu in yakalanan:
        assert not egress_pii_var_mi(sorgu), f"egress-PII web'e sızdı: {sorgu!r}"
    # Temiz iddia GERÇEKTEN gönderildi (vacuous değil).
    assert any("enflasyon" in s.lower() for s in yakalanan)
    # Adres iddiası web'e GİTMEDİ (maskelenemez PII → bloklandı).
    assert not any("caddesinde" in s.lower() for s in yakalanan)


def test_kimlik_belgesi_baglami_egress_bloklanir(monkeypatch):
    """review tur-3 HIGH: kimlik-BELGESİ bağlamı (doğum tarihi/T.C. kimlik no/pasaport + ad-soyad)
    web'e GİTMEMELİ — anonimleştir maskeleyemez (isim NER Faz 5), egress fail-closed bloklamalı.
    Bağımsız davranışsal kanary (egress_pii_var_mi internals'ına dayanmaz): yakalanan'da YOK."""
    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    metin = (
        "Müvekkil Ahmet Yılmaz'ın doğum tarihi 1 Ocak 1980 olarak kayıtlı. "  # doğum tarihi → blok
        "Sanığın T.C. kimlik numarası duruşmada okundu. "  # T.C. kimlik no → blok
        "Pasaport numarası dosyaya eklendi."  # pasaport no → blok
    )
    fact_check(metin, _SatirLLM(), web)
    # Hiçbir kimlik-belgesi iddiası web'e gitmemeli.
    for s in yakalanan:
        assert "doğum tarihi" not in s.lower()
        assert "kimlik numara" not in s.lower()
        assert "pasaport numara" not in s.lower()
        assert not egress_pii_var_mi(s)


def test_kimlik_baglam_fail_closed_bloklanir(monkeypatch):
    """review tur-4 HIGH: 'nüfus' hem demografik ('Türkiye nüfusu') hem kimlik-BELGESİ
    ('nüfus cüzdanı'/'nüfusa kayıtlı Ahmet') olabilir — NER'siz ayrılamaz. KVKK FAIL-CLOSED
    (değişmez #1): TÜM kimlik-bağlam web'e GİTMEZ (ad-soyad+nüfus-belgesi sızıntısı önlenir)."""
    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    metin = (
        "Enflasyon yüzde 40 arttı. "  # TEMİZ → web'e GİTMELİ (oracle non-vacuous garantisi)
        "Müvekkil Ahmet Yılmaz nüfus cüzdanı fotokopisi dosyada. "  # kimlik-belgesi → blok
        "Sanık Mehmet Demir nüfus kayıt örneğine göre Beşiktaş'a kayıtlı. "  # belge → blok
        "Türkiye nüfusu 85 milyona ulaştı."  # demografik de fail-closed blok (NER Faz 5)
    )
    fact_check(metin, _SatirLLM(), web)
    # Oracle BOŞ DEĞİL (review tur-5 MED vacuous-fix): temiz iddia gönderildi → döngü koşar.
    assert yakalanan
    assert any("enflasyon" in s.lower() for s in yakalanan)  # temiz iddia GİTTİ
    # Hiçbir kimlik-bağlam iddiası (ad+nüfus-belgesi dahil) web'e gitmemeli.
    for s in yakalanan:
        assert "ahmet yılmaz" not in s.lower()
        assert "mehmet demir" not in s.lower()
        assert "nüfus" not in s.lower()
        assert not egress_pii_var_mi(s)


def test_pii_iddia_egress_bloklanir(monkeypatch):
    """Maskelenemez PII (adres) içeren iddia web'e HİÇ gönderilmemeli (deny-by-default)."""
    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    metin = "Müvekkil Ankara Kızılay Mahallesinde ikamet etmektedir."
    sonuc, _ = fact_check(metin, _SatirLLM(), web)
    assert yakalanan == []  # adres → hiç web çağrısı yok
    assert sonuc
    assert all("pii" in it.get("gerekce", "").lower() or it["karar"] == "BELİRSİZ" for it in sonuc)


def test_maskelenebilir_pii_maskelenip_gider(monkeypatch):
    """email/tckn/telefon anonimleştir'le maskelenir → maskeli sorgu web'e gider (ham PII yok)."""
    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    fact_check("Enflasyon ahmet@example.com kaynağına göre yüzde 40 arttı.", _SatirLLM(), web)
    assert yakalanan  # maskelenip gönderildi
    for sorgu in yakalanan:
        assert "ahmet@example.com" not in sorgu  # ham email maskelendi
        assert not egress_pii_var_mi(sorgu)


def test_ner_kisi_adi_web_sorgusunu_bloklar(monkeypatch):
    """Faz 5 NER katmanı: çıplak ad-soyad pattern-gate'i ATLATIR (pii_gate kaçırır —
    GÜNCELLEME 5/6 bloker). NER 'Ahmet Yılmaz'ı görür → bu iddia web'e GİTMEZ (fail-closed);
    temiz iddia GİDER (over-block yok, oracle non-vacuous)."""
    from ytcore.router.ner import FakeNER

    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    metin = (
        "Enflasyon 2025 yılında yüzde 40 arttı. "  # temiz → gönderilmeli
        "Ahmet Yılmaz şirketi 2020 yılında 5 milyon dolara sattı."  # çıplak ad → NER blok
    )
    sonuc, _ = fact_check(metin, _SatirLLM(), web, ner=FakeNER())
    assert any("enflasyon" in s.lower() for s in yakalanan)  # temiz iddia GİTTİ
    assert all("Ahmet Yılmaz" not in s for s in yakalanan)  # ad web'e SIZMADI
    assert any("ner" in (i.get("gerekce") or "").lower() for i in sonuc)  # dürüst gerekçe


def test_ner_guard_mutasyon_kontrolu(monkeypatch):
    """MUTASYON-KONTROL (Faz 3/4 dersi): ner=None (guard yok) iken aynı ad web'e SIZAR —
    üstteki test gerçekten NER guard'ını ölçüyor; guard silinirse o test KIRMIZI döner."""
    yakalanan: list[str] = []
    monkeypatch.setattr(SerperSearch, "ara_durumlu", _spy(yakalanan))
    web = SerperSearch(api_key="sahte-anahtar")
    fact_check(
        "Ahmet Yılmaz şirketi 2020 yılında 5 milyon dolara sattı.", _SatirLLM(), web, ner=None
    )
    assert any("Ahmet Yılmaz" in s for s in yakalanan)  # guard'sız sızıntı KANITI

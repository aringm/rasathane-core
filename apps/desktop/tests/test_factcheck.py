from __future__ import annotations

from ytcore.content.llm import FakeLLM
from ytcore.intel.factcheck import fact_check, iddialari_cikar
from ytcore.intel.websearch import FakeWebSearch, SerperSearch


def test_iddialari_cikar_cumle_tabanli():
    iddialar = iddialari_cikar("Enflasyon yüzde 40 arttı. Faiz indirildi.", FakeLLM())
    assert len(iddialar) >= 1


def test_iddialari_cikar_bos():
    assert iddialari_cikar("", FakeLLM()) == []


def test_fact_check_web_yok_durust(monkeypatch):
    # Web anahtarsız (gerçek Serper) → BELİRSİZ + web_yok (sahte verdict değil).
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    sonuc, durum = fact_check("Enflasyon yüzde 40 arttı.", FakeLLM(), SerperSearch())
    assert durum == "web_yok"
    assert sonuc
    assert all(i["karar"] == "BELİRSİZ" for i in sonuc)
    assert all(i["kaynaklar"] == [] for i in sonuc)  # kaynak yok


def test_fact_check_fake_web_verdict():
    sonuc, durum = fact_check("Enflasyon yüzde 40 arttı.", FakeLLM(), FakeWebSearch())
    assert durum == "uretildi"
    assert sonuc and "karar" in sonuc[0]
    assert sonuc[0]["kaynaklar"]  # FakeWebSearch URL'leri


def test_fact_check_icerik_yok():
    sonuc, durum = fact_check("", FakeLLM(), FakeWebSearch())
    assert durum == "icerik_yok"
    assert sonuc == []


def test_cloud_verdict_kullanilir():
    # Faz 5 Mod B: cloud verildiğinde verdict cloud'dan gelir (token sayaçlı sahte istemci).
    from ytcore.router.cloud_client import CloudYanit

    class SahteCloud:
        def __init__(self):
            self.cagri_sayisi = 0
            self.toplam_girdi_token = 0
            self.toplam_cikti_token = 0

        def cagir(self, metin, system, max_tokens=1024):
            self.cagri_sayisi += 1
            self.toplam_girdi_token += 50
            self.toplam_cikti_token += 3
            return CloudYanit("DESTEKLİYOR", 50, 3)

    cloud = SahteCloud()
    sonuc, durum = fact_check(
        "Enflasyon yüzde 40 arttı.", FakeLLM(), FakeWebSearch(), cloud=cloud
    )
    assert cloud.cagri_sayisi >= 1  # verdict cloud'dan geldi
    assert any(i["karar"] == "DESTEKLİYOR" for i in sonuc)
    assert any("cloud" in (i.get("gerekce") or "").lower() for i in sonuc)  # dürüst kaynak izi


def test_cloud_verdict_hatasi_local_fallbacka_duser():
    # Cloud reddi (KVKK guard/ağ) analizi ÇÖKERTMEZ → local qwen verdict'e graceful düşer.
    from ytcore.router.cloud_client import KVKKEgressEngellendi

    class PatlayanCloud:
        cagri_sayisi = 0
        toplam_girdi_token = 0
        toplam_cikti_token = 0

        def cagir(self, metin, system, max_tokens=1024):
            raise KVKKEgressEngellendi("test")

    sonuc, durum = fact_check(
        "Enflasyon yüzde 40 arttı.", FakeLLM(), FakeWebSearch(), cloud=PatlayanCloud()
    )
    assert sonuc and all(
        i["karar"] in ("DESTEKLİYOR", "ÇELİŞİYOR", "BELİRSİZ") for i in sonuc
    )


class _KucukHarfVerdictLLM:
    """Karar kelimesini kucuk/karisik harf donduren LLM (TR upper() tuzagi regresyonu)."""

    def uret(self, sistem: str, kullanici: str, *, model: str | None = None) -> str:
        if "verdict" in sistem:
            return "Destekliyor."
        return kullanici  # claim cikarimi: echo


def test_verdict_kucuk_harf_tr_katlama():
    # review tur-1 HIGH: "destekliyor".upper()="DESTEKLIYOR" (ASCII I) != "DESTEKLIYOR"(I-noktali)
    # -> sessiz BELIRSIZ. TR katlama ile kucuk/karisik harf yanit da eslesmelidir.
    sonuc, durum = fact_check(
        "Enflasyon resmi verilere gore 2025 yilinda yuzde 40 artti.",
        _KucukHarfVerdictLLM(),
        FakeWebSearch(),
    )
    assert any(i["karar"] == "DESTEKLİYOR" for i in sonuc)


def test_cloud_verdict_kod_hatasi_gorunur_coker():
    # review tur-1 MED: cloud fallback'i KOD_HATALARI'ni (NameError/AttributeError) YUTMAMALI
    # (mock-drift / typo sessiz no-op olur). Yalniz cevre hatalari (KVKK/ag) local'e duser.
    class BozukCloud:
        def cagir(self, metin, system, max_tokens=1024):
            raise AttributeError("mock drift: yanlis imza")

    import pytest

    with pytest.raises(AttributeError):
        fact_check(
            "Enflasyon yuzde 40 artti.", FakeLLM(), FakeWebSearch(), cloud=BozukCloud()
        )


def test_karar_bul_konum_bazli_ilk_eslesme():
    # review tur-2 LOW: çok-kelimeli yanıtta metinde ÖNCE geçen karar kazanır
    # (sabit-öncelik "kanıtlar çelişiyor; destekliyor diyemeyiz"de yanlış seçerdi).
    from ytcore.intel.factcheck import _karar_bul

    assert _karar_bul("Kanıtlara göre çelişiyor; destekliyor diyemeyiz.") == "ÇELİŞİYOR"
    assert _karar_bul("Destekliyor.") == "DESTEKLİYOR"  # küçük-harf TR katlaması
    assert _karar_bul("BELIRSIZ") == "BELİRSİZ"  # ASCII-I katlaması
    assert _karar_bul("alakasız yanıt") is None

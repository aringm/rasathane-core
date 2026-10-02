from __future__ import annotations

from ytcore.content.llm import FakeLLM
from ytcore.intel.kisisel import kisisel_analiz
from ytcore.intel.memory import FakeMemoryStore


def test_kisisel_persona_yok_jenerik(tmp_path):
    # user.md/memory.md yok → graceful jenerik lens (çökmez, boş değil).
    metin, durum = kisisel_analiz(
        "Sözleşme hukuku temeldir.",
        FakeLLM(),
        FakeMemoryStore(),
        kullanici_base=tmp_path / "_kullanici",
    )
    assert durum == "uretildi"
    assert metin.strip()  # boş değil (boş≠başarı)


def test_kisisel_icerik_yok():
    metin, durum = kisisel_analiz("", FakeLLM(), FakeMemoryStore(), kullanici_base=None)
    assert durum == "icerik_yok"
    assert metin == ""


def test_kisisel_persona_var_inject(tmp_path):
    base = tmp_path / "_kullanici"
    base.mkdir(parents=True)
    (base / "user.md").write_text(
        "Av. Mehmet Arın Gülüm — sözleşme hukuku uzmanı.", encoding="utf-8"
    )
    metin, durum = kisisel_analiz(
        "Sözleşme hukuku temeldir.", FakeLLM(), FakeMemoryStore(), kullanici_base=base
    )
    assert durum == "uretildi"
    assert metin.strip()


def test_kisisel_gecmis_baglanti(tmp_path):
    m = FakeMemoryStore()
    m.ekle("Önceki analiz: sözleşme feshi davası.", {"video_id": "v0"})
    metin, durum = kisisel_analiz(
        "Sözleşme hukuku temeldir.", FakeLLM(), m, kullanici_base=tmp_path / "_k"
    )
    assert durum == "uretildi"
    assert "sözleşme" in metin.lower()  # retrieval çalıştı (geçmiş bağlantı bağlamı)

from __future__ import annotations

from ytcore.content.llm import FakeLLM
from ytcore.intel.kisisel import kisisel_analiz
from ytcore.intel.memory import Ani, FakeMemoryStore


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


def test_current_source_prompt_isolated_from_retrieved_history():
    calls = []

    class CaptureLLM:
        def uret(self, sistem, kullanici, *, model=None):
            calls.append((sistem, kullanici))
            return "Yalnız mevcut akademik özetin analizi."

    class History:
        def ara(self, sorgu, k=5):
            assert sorgu == "Transformer akademik özeti."
            assert k == 3
            return [
                Ani(
                    "YEPDİS: eski enerji yönetmeliği değerlendirmesi.",
                    {
                        "video_id": "web:old-regulation",
                        "kaynak_turu": "web",
                        "kaynak_url": "https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm",
                        "baslik": "Eski enerji düzenlemesi analizi",
                    },
                )
            ]

    text, status = kisisel_analiz(
        "Transformer akademik özeti.",
        CaptureLLM(),
        History(),
        kullanici_base=None,
        kaynak_turu="arxiv",
    )
    assert status == "uretildi"
    assert calls[0][1] == "İÇERİK:\nTransformer akademik özeti."
    assert "YEPDİS" not in str(calls)
    current, history = text.split("## Geçmiş Analiz Kayıtları", 1)
    assert current.strip() == "Yalnız mevcut akademik özetin analizi."
    assert "güncel kaynağın kanıtı değildir" in history
    assert "Kaynak türü: web" in history
    assert "web:old-regulation" in history
    assert "https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm" in history
    assert "YEPDİS" in history


def test_history_without_url_does_not_invent_source_link():
    history = FakeMemoryStore()
    history.ekle("Transformer önceki yorum.", {"video_id": "web:legacy-hash"})
    text, status = kisisel_analiz("Transformer yeni özet.", FakeLLM(), history, kullanici_base=None)
    assert status == "uretildi"
    assert "Kaynak türü: web" in text
    assert "web:legacy-hash" in text
    assert "Kaynak bağlantısı bu eski kayıtta yok." in text
    assert "https://" not in text


def test_history_link_from_stored_text_remains_separate_and_safe():
    history = FakeMemoryStore()
    history.ekle(
        "Transformer eski kayıt.\nKaynak: https://arxiv.org/abs/1706.03762v7\n"
        "Yanıltıcı link: javascript:alert(1)",
        {"video_id": "arxiv:1706.03762v7"},
    )
    text, _ = kisisel_analiz("Transformer yeni özet.", FakeLLM(), history, kullanici_base=None)
    assert "Kaynak türü: arxiv" in text
    assert "Kaynak: https://arxiv.org/abs/1706.03762v7" in text
    assert "## Geçmiş Analiz Kayıtları" in text
    assert "[javascript" not in text

from __future__ import annotations

from ytcore.content.dokum import DokumBolum, baslik_uret, baslik_uret_llm, dokum_derle
from ytcore.content.llm import FakeLLM
from ytcore.infra.embedding import FakeEmbedding


def test_baslik_uret_keywordden():
    b = baslik_uret(["sözleşme hukuku", "irade"], ["Sözleşme önemlidir."])
    assert b.strip()
    assert "sözleşme" in b.lower()


def test_baslik_uret_keyword_yok_cumleden():
    b = baslik_uret([], ["Bu bir başlangıç cümlesidir."])
    assert b.strip()
    assert b != "Bölüm"


def test_baslik_uret_hicbiri():
    assert baslik_uret([], []) == "Bölüm"


def test_dokum_derle_bolum_uretir():
    metin = (
        "Sözleşme hukuku borçlar hukukunun temelidir. İrade serbestisi önemlidir. "
        "Tazminat hukuku ayrı bir daldır. Haksız fiil sorumluluğu doğurur."
    )
    bolumler = dokum_derle(metin, FakeEmbedding(), segment_sn=None)
    assert len(bolumler) >= 1
    assert all(isinstance(b, DokumBolum) for b in bolumler)
    assert all(b.metin.strip() for b in bolumler)


def test_dokum_derle_bos_metin():
    assert dokum_derle("", FakeEmbedding(), segment_sn=None) == []


def test_dokum_derle_timestamp_haritalama():
    metin = "Bir cümle. İki cümle. Üç cümle. Dört cümle."
    bolumler = dokum_derle(metin, FakeEmbedding(), segment_sn=[0, 10, 20, 30])
    assert bolumler[0].baslangic_sn == 0


def test_baslik_uret_llm_kullanir():
    # LLM başlık döndürür (FakeLLM 'başlık' görevini sezer)
    b = baslik_uret_llm(
        "Sözleşme hukuku temeldir.", FakeLLM(), ["sözleşme"], ["Sözleşme hukuku temeldir."]
    )
    assert b.strip()


def test_baslik_uret_llm_bos_fallback():
    class BosLLM:
        def uret(self, sistem, kullanici, *, model=None):
            return ""

    b = baslik_uret_llm("metin", BosLLM(), ["sözleşme"], ["metin."])
    assert b == "Sözleşme"  # fallback baslik_uret(keywords)


def test_baslik_uret_llm_hata_fallback():
    class PatlaLLM:
        def uret(self, sistem, kullanici, *, model=None):
            raise RuntimeError("ollama down")

    b = baslik_uret_llm("metin", PatlaLLM(), ["tazminat"], ["metin."])
    assert b == "Tazminat"  # model/ağ ham hata → deterministik fallback


def test_baslik_uret_llm_kod_bug_reraise():
    # Kontrat ihlali (non-str dönüş) → AttributeError re-raise (sessizce fallback'e DÜŞME)
    import pytest

    class NoneLLM:
        def uret(self, sistem, kullanici, *, model=None):
            return None  # .strip() AttributeError

    with pytest.raises(AttributeError):
        baslik_uret_llm("metin", NoneLLM(), ["x"], ["metin."])


def test_dokum_derle_llm_basligi():
    metin = "Sözleşme hukuku temeldir. İrade serbestisi önemlidir. Tazminat ayrı daldır."
    bolumler = dokum_derle(metin, FakeEmbedding(), llm=FakeLLM())
    assert all(b.baslik.strip() for b in bolumler)


def test_dokum_embeddings_finish_before_titles_and_preserve_segment_contract(monkeypatch):
    from ytcore.content import dokum

    calls = []

    class ObservedEmbedding(FakeEmbedding):
        def embed(self, texts):
            calls.append(("embed", list(texts)))
            return super().embed(texts)

    class ObservedLLM:
        def uret(self, system, text, *, model=None):
            calls.append(("llm", text, model))
            if text.startswith("Üçüncü"):
                raise RuntimeError("Geçici model hatası")
            return "Birinci Bölüm" if text.startswith("Birinci") else ""

    def segments(sentences, embed):
        embed.embed(sentences)
        return [[0, 1], [2], [3]]

    def keywords(text, *, ust_n, embed):
        assert ust_n == 5
        embed.embed([text])
        return [{"Birinci": "birinci", "İkinci": "borçlar", "Üçüncü": "tazminat"}[text.split()[0]]]

    monkeypatch.setattr(dokum, "segmentle", segments)
    monkeypatch.setattr(dokum, "keyword_cikar", keywords)
    result = dokum_derle(
        "Birinci cümle. Ek cümle. İkinci cümle. Üçüncü cümle.",
        ObservedEmbedding(),
        segment_sn=[5, 10, 25, 40],
        llm=ObservedLLM(),
        model="test-map-model",
    )
    assert [call[0] for call in calls] == ["embed"] * 4 + ["llm"] * 3
    assert all(call[2] == "test-map-model" for call in calls if call[0] == "llm")
    assert result == [
        DokumBolum(5, "Birinci Bölüm", "Birinci cümle. Ek cümle.", ["birinci"]),
        DokumBolum(25, "Borçlar", "İkinci cümle.", ["borçlar"]),
        DokumBolum(40, "Tazminat", "Üçüncü cümle.", ["tazminat"]),
    ]

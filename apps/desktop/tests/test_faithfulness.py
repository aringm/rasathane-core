from __future__ import annotations

from ytcore.content.faithfulness import faithfulness, iddialari_cikar


class _EvetLLM:
    def uret(self, sistem, kullanici, *, model=None):
        return "EVET"


class _HayirLLM:
    def uret(self, sistem, kullanici, *, model=None):
        return "HAYIR"


def test_iddialari_cikar():
    assert len(iddialari_cikar("Birinci iddia. İkinci iddia.")) == 2


def test_faithfulness_hepsi_destekli():
    skor, durum = faithfulness("İddia bir. İddia iki.", "kaynak", _EvetLLM(), esik=0.8)
    assert skor == 1.0
    assert durum == "gecti"


def test_faithfulness_hicbiri_destekli():
    skor, durum = faithfulness("İddia bir. İddia iki.", "kaynak", _HayirLLM(), esik=0.8)
    assert skor == 0.0
    assert durum == "esik_alti"


def test_faithfulness_bos_ozet():
    skor, durum = faithfulness("", "kaynak", _EvetLLM())
    assert durum == "ozet_yok"
    assert skor == 0.0


def test_faithfulness_uzun_kaynak_embed_chunk():
    # MED #11: uzun kaynak + embed → iddia-başına ilgili-chunk seçimi (naif [:6000] kesimi yok)
    from ytcore.infra.embedding import FakeEmbedding

    kaynak = "Sözleşme hukuku temeldir. " * 400  # >6000 karakter
    skor, durum = faithfulness(
        "Sözleşme hukuku temeldir.", kaynak, _EvetLLM(), embed=FakeEmbedding()
    )
    assert skor == 1.0 and durum == "gecti"


def test_faithfulness_embed_chunk_judge_baglami_kaynaktan(monkeypatch):
    # embed yolu judge'a kaynak içeriğini veriyor mu (boş/kesik değil)
    yakalanan = []

    class KayitLLM:
        def uret(self, sistem, kullanici, *, model=None):
            yakalanan.append(kullanici)
            return "EVET"

    from ytcore.infra.embedding import FakeEmbedding

    kaynak = "Tazminat hukuku haksız fiilden doğar. " * 300
    faithfulness("Tazminat hukuku haksız fiilden doğar.", kaynak, KayitLLM(), embed=FakeEmbedding())
    assert yakalanan and "Tazminat" in yakalanan[0]


def test_all_evidence_embeddings_precede_judges_with_same_prompts_score_and_model(monkeypatch):
    import importlib

    module = importlib.import_module("ytcore.content.faithfulness")
    chunks = ["Birinci kaynak cümlesi.", "İkinci kaynak cümlesi.", "Üçüncü kaynak cümlesi."]
    claims = ["İlk iddia.", "İkinci iddia.", "Son iddia."]
    events = []

    class Embed:
        def embed(self, texts):
            events.append(("embed", texts))
            if texts == chunks:
                return [[1.0, 0.0], [0.0, 1.0], [0.8, 0.8]]
            return [{claims[0]: [1.0, 0.0], claims[1]: [0.0, 1.0], claims[2]: [1.0, 1.0]}[texts[0]]]

    class Judge:
        def uret(self, system, text, *, model=None):
            events.append(("llm", text, model))
            return "hayır" if text.startswith("İDDİA: İkinci") else "  EVET.  "

    monkeypatch.setattr(module, "semantic_chunk", lambda *_args, **_kw: chunks)
    result = faithfulness(
        " ".join(claims),
        "Uzun kaynak cümlesi. " * 400,
        Judge(),
        embed=Embed(),
        model="judge-model",
        ust_chunk=2,
    )
    assert [event[0] for event in events] == ["embed"] * 4 + ["llm"] * 3
    prompts = [event[1] for event in events if event[0] == "llm"]
    assert prompts == [
        f"İDDİA: {claims[0]}\n\nKAYNAK: {chunks[0]}\n{chunks[2]}",
        f"İDDİA: {claims[1]}\n\nKAYNAK: {chunks[1]}\n{chunks[2]}",
        f"İDDİA: {claims[2]}\n\nKAYNAK: {chunks[0]}\n{chunks[2]}",
    ]
    assert all(event[2] == "judge-model" for event in events if event[0] == "llm")
    assert result == (2 / 3, "esik_alti")


def test_short_source_keeps_original_context_without_embedding():
    class UnusedEmbed:
        def embed(self, texts):
            raise AssertionError("Kısa kaynak embedding gerektirmez")

    prompts = []

    class Judge:
        def uret(self, system, text, *, model=None):
            prompts.append(text)
            return "EVET"

    assert faithfulness("İddia bir. İddia iki.", "Kısa kaynak.", Judge(), embed=UnusedEmbed()) == (
        1.0,
        "gecti",
    )
    assert prompts == [
        "İDDİA: İddia bir.\n\nKAYNAK: Kısa kaynak.",
        "İDDİA: İddia iki.\n\nKAYNAK: Kısa kaynak.",
    ]

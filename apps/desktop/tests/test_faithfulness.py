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

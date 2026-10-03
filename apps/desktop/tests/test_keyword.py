from __future__ import annotations

from ytcore.content.keyword import keyword_cikar, keyword_f1
from ytcore.infra.embedding import FakeEmbedding


def test_keyword_cikar_tr():
    metin = (
        "Sözleşme hukuku borçlar hukukunun temelidir. Sözleşme serbestisi ve irade "
        "serbestisi önemli ilkelerdir. Borçlar hukuku sözleşmeleri düzenler."
    )
    kw = keyword_cikar(metin, ust_n=5)
    assert len(kw) >= 1
    birlesik = " ".join(kw).lower()
    assert "sözleşme" in birlesik or "borçlar" in birlesik or "hukuk" in birlesik


def test_keyword_cikar_bos():
    assert keyword_cikar("", ust_n=5) == []


def test_keyword_cikar_mmr_calisir():
    metin = (
        "Sözleşme hukuku borçlar hukukunun temelidir. İrade serbestisi önemlidir. "
        "Tazminat hukuku ayrı bir daldır."
    )
    kw = keyword_cikar(metin, ust_n=3, embed=FakeEmbedding())
    assert 1 <= len(kw) <= 3


def test_keyword_f1_mukemmel():
    assert keyword_f1(["sözleşme", "borçlar"], ["sözleşme", "borçlar"])["f1"] == 1.0


def test_keyword_f1_kismi():
    f1 = keyword_f1(["sözleşme", "x"], ["sözleşme", "borçlar"])["f1"]
    assert 0.0 < f1 < 1.0


def test_keyword_f1_bos_golden():
    assert keyword_f1(["a"], [])["f1"] == 0.0


def test_keyword_f1_buyuk_kucuk_harf():
    assert keyword_f1(["Sözleşme"], ["sözleşme"])["f1"] == 1.0

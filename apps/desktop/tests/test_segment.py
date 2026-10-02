from __future__ import annotations

import pytest
from ytcore.content.segment import (
    cumlelere_bol,
    etiketler_uret,
    pk,
    segmentle,
    windowdiff,
)
from ytcore.infra.embedding import FakeEmbedding


def test_cumlelere_bol():
    assert cumlelere_bol("Bir. İki! Üç? Dört.") == ["Bir.", "İki!", "Üç?", "Dört."]


def test_cumlelere_bol_bos():
    assert cumlelere_bol("   ") == []


def test_cumlelere_bol_son_artik_noktasiz():
    # noktalama olmadan biten son parça da yakalanmalı
    assert cumlelere_bol("Tam cümle. Yarım") == ["Tam cümle.", "Yarım"]


def test_segmentle_tek_segment_kisa():
    assert segmentle(["Tek cümle."], FakeEmbedding()) == [[0]]


def test_segmentle_bos():
    assert segmentle([], FakeEmbedding()) == []


def test_segmentle_etiket_eksiksiz():
    cumleler = [f"Cümle {i}." for i in range(10)]
    segs = segmentle(cumleler, FakeEmbedding())
    duz = sorted(i for s in segs for i in s)
    assert duz == list(range(10))
    assert len(segs) >= 1


def test_etiketler_uret():
    assert etiketler_uret([[0, 1], [2, 3]], 4) == [0, 0, 1, 1]


def test_pk_mukemmel_eslesme_sifir():
    etiket = [0, 0, 1, 1, 2, 2]
    assert pk(etiket, etiket) == 0.0


def test_pk_kotu_eslesme_pozitif():
    ref = [0, 0, 0, 1, 1, 1]
    hyp = [0, 1, 0, 1, 0, 1]
    assert pk(ref, hyp) > 0.0


def test_pk_tek_birim():
    assert pk([0], [0]) == 0.0


def test_windowdiff_mukemmel_sifir():
    etiket = [0, 0, 1, 1, 2, 2]
    assert windowdiff(etiket, etiket) == 0.0


def test_windowdiff_farkli_pozitif():
    ref = [0, 0, 0, 1, 1, 1]
    hyp = [0, 1, 2, 3, 4, 5]
    assert windowdiff(ref, hyp) > 0.0


def test_pk_uzunluk_uyumsuzlugu_raise():
    # Yapısal veri/kod bug → sessizce 1.0 dönüp kök-nedeni gizleme (review MED)
    with pytest.raises(ValueError, match="uzunluk"):
        pk([0, 0, 1], [0, 0, 1, 1])


def test_windowdiff_uzunluk_uyumsuzlugu_raise():
    with pytest.raises(ValueError, match="uzunluk"):
        windowdiff([0, 0, 1], [0, 0, 1, 1])


def test_pk_bitisik_olmayan_id_dogru():
    # ref=[0,0,1,1,0,0] (A/B/C, id 0 tekrar kullanılmış) ile hyp=[0,0,1,1,2,2] AYNI
    # segmentasyon (sınırlar {1,3}) → Pk=0 olmalı (run-bazlı renormalize fix, review MED)
    assert pk([0, 0, 1, 1, 0, 0], [0, 0, 1, 1, 2, 2]) == 0.0
    assert windowdiff([0, 0, 1, 1, 0, 0], [0, 0, 1, 1, 2, 2]) == 0.0


def test_pk_bitisik_olmayan_id_farkli_segmentasyon():
    # ref=[0,0,1,1,0,0] (3 segment) vs hyp=[0,0,0,0,0,0] (1 segment) → farklı → Pk>0
    assert pk([0, 0, 1, 1, 0, 0], [0, 0, 0, 0, 0, 0]) > 0.0

from __future__ import annotations

from ytcore.infra.rrf import rrf_birlestir


def test_rrf_tek_siralama_sira_korur():
    # Tek sıralama → RRF skoru sırayı korur (en üst en yüksek).
    sonuc = rrf_birlestir([["a", "b", "c"]], k=60)
    assert [d for d, _ in sonuc] == ["a", "b", "c"]


def test_rrf_iki_siralama_konsensus_yukselir():
    # İki sıralamada da üstte olan belge en yükseğe çıkar.
    s1 = ["a", "b", "c"]
    s2 = ["b", "a", "d"]
    sonuc = dict(rrf_birlestir([s1, s2], k=60))
    assert sonuc["a"] > sonuc["c"]  # a iki listede de üstte
    assert sonuc["b"] > sonuc["d"]  # b iki listede, d tek listede
    assert set(sonuc) == {"a", "b", "c", "d"}  # birleşim


def test_rrf_bos():
    assert rrf_birlestir([], k=60) == []
    assert rrf_birlestir([[], []], k=60) == []


def test_rrf_k_etkisi():
    # k büyükse rank farkları yumuşar; formül 1/(k+rank).
    s = dict(rrf_birlestir([["a", "b"]], k=60))
    assert abs(s["a"] - 1 / 60) < 1e-9  # rank 0 → 1/(60+0)
    assert abs(s["b"] - 1 / 61) < 1e-9  # rank 1 → 1/(60+1)

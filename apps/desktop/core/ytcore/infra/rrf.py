from __future__ import annotations


def rrf_birlestir(siralamalar: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion: birden çok sıralı belge-id listesini tek skora birleştir.

    skor(d) = Σ_r 1/(k + rank_r(d))  (rank 0-tabanlı). Hibrit retrieval'da anlamsal
    (LanceDB) + keyword (FTS5) sıralamalarını birleştirir; k=60 literatür-standart
    (büyük k rank farklarını yumuşatır). Skora göre azalan sırada (belge, skor) döndür.
    """
    skorlar: dict[str, float] = {}
    for siralama in siralamalar:
        for rank, belge in enumerate(siralama):
            skorlar[belge] = skorlar.get(belge, 0.0) + 1.0 / (k + rank)
    return sorted(skorlar.items(), key=lambda kv: -kv[1])

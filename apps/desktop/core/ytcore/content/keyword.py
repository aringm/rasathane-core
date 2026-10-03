from __future__ import annotations

from ytcore.infra.embedding import EmbeddingProvider


def keyword_cikar(
    metin: str, *, ust_n: int = 10, embed: EmbeddingProvider | None = None
) -> list[str]:
    """YAKE ile TR keyword (saf CPU, torch yok). embed verilirse MMR çeşitlilik reranking
    (KeyBERT-eşi, opsiyonel). Boş metin → [].

    NOT: TR keyword kalitesi (BERTurk F1=97.77) yalnız akademik korpusta (A03-doğrulama);
    konuşmalı TR'de düşer → eşik kendi veride ölçülür (eval moat).
    """
    if not metin.strip():
        return []
    import yake

    cikaran = yake.KeywordExtractor(lan="tr", n=2, top=ust_n * 3, dedupLim=0.7)
    ham = cikaran.extract_keywords(metin)  # [(kw, skor)] — düşük skor=iyi
    adaylar = [kw for kw, _ in sorted(ham, key=lambda x: x[1])]
    if not adaylar:
        return []
    if embed is None:
        return adaylar[:ust_n]
    return _mmr(metin, adaylar, embed, ust_n)


def _mmr(
    metin: str, adaylar: list[str], embed: EmbeddingProvider, ust_n: int, lam: float = 0.6
) -> list[str]:
    """Maximal Marginal Relevance: belge-ilgisi vs aday-çeşitliliği dengesi."""
    vektorler = embed.embed([metin, *adaylar])
    belge = vektorler[0]
    aday_v = vektorler[1:]

    def benz(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=False))

    secili: list[int] = []
    kalan = list(range(len(adaylar)))
    while kalan and len(secili) < ust_n:
        en_iyi: int | None = None
        en_iyi_skor = -1e9
        for i in kalan:
            ilgi = benz(aday_v[i], belge)
            ceza = max((benz(aday_v[i], aday_v[j]) for j in secili), default=0.0)
            skor = lam * ilgi - (1 - lam) * ceza
            if skor > en_iyi_skor:
                en_iyi_skor, en_iyi = skor, i
        assert en_iyi is not None
        secili.append(en_iyi)
        kalan.remove(en_iyi)
    return [adaylar[i] for i in secili]


def keyword_f1(tahmin: list[str], golden: list[str]) -> dict[str, float]:
    """Set-tabanlı P/R/F1 (küçük-harf normalize). Golden boş → F1=0 (eval moat)."""
    t = {k.strip().lower() for k in tahmin if k.strip()}
    g = {k.strip().lower() for k in golden if k.strip()}
    if not g:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    kesisim = len(t & g)
    p = kesisim / len(t) if t else 0.0
    r = kesisim / len(g)
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return {"precision": p, "recall": r, "f1": f1}

from __future__ import annotations

import re

from ytcore.infra.embedding import EmbeddingProvider

# Cümle bölücü: nokta/ünlem/soru/üç-nokta ile biten + son artık. TR'de yeterli.
_CUMLE = re.compile(r"[^.!?…]+[.!?…]+|\S[^.!?…]*$")


def cumlelere_bol(metin: str) -> list[str]:
    """Metni cümlelere böl (TR noktalama). Boş → []."""
    if not metin.strip():
        return []
    return [m.group().strip() for m in _CUMLE.finditer(metin) if m.group().strip()]


def benzerlik(a: list[float], b: list[float]) -> float:
    """Kosinüs ≈ nokta-çarpım (vektörler normalize — FakeEmbedding/bge-m3)."""
    return sum(x * y for x, y in zip(a, b, strict=False))


_benzerlik = benzerlik  # geriye-dönük iç ad


def semantic_chunk(
    cumleler: list[str], embed: EmbeddingProvider, *, hedef_kar: int = 4000, ortusme: int = 1
) -> list[str]:
    """Cümleleri ~hedef_kar karakterlik parçalara böl (cümle sınırında, %ortüşme). Boş → [].

    Karakter-bütçeli, cümle-hizalı (context penceresini aşmadan map/judge'a besler). Overlap
    chunk'lar-arası bağlam kaybını azaltır. (segment.py'de: özet + faithfulness ortak kullanır.)
    """
    if not cumleler:
        return []
    parcalar: list[str] = []
    gecerli: list[str] = []
    uzunluk = 0
    for c in cumleler:
        if uzunluk + len(c) > hedef_kar and gecerli:
            parcalar.append(" ".join(gecerli))
            gecerli = gecerli[-ortusme:] if ortusme else []
            uzunluk = sum(len(x) for x in gecerli)
        gecerli.append(c)
        uzunluk += len(c)
    if gecerli:
        parcalar.append(" ".join(gecerli))
    return parcalar


def segmentle(
    cumleler: list[str], embed: EmbeddingProvider, *, esik_k: float = 1.0
) -> list[list[int]]:
    """Embedding-tabanlı segmentasyon (TextTiling/TreeSeg-lite): ardışık cümle benzerliği
    ortalama−k·std eşiğinin altına düşünce konu sınırı. Çıktı = cümle index gruplarının
    listesi. Tek/iki cümle → tek segment (boş döküm guard'ı — boş≠başarı).

    NOT: TreeSeg TR'de DOĞRULANMAMIŞ (A03-doğrulama) → eşik TR eval ile kalibre edilir.
    """
    n = len(cumleler)
    if n == 0:
        return []
    if n <= 2:
        return [list(range(n))]
    vekt = embed.embed(cumleler)
    benz = [_benzerlik(vekt[i], vekt[i + 1]) for i in range(n - 1)]
    ort = sum(benz) / len(benz)
    var = sum((b - ort) ** 2 for b in benz) / len(benz)
    std = var**0.5
    esik = ort - esik_k * std
    sinirlar = [i for i, b in enumerate(benz) if b < esik]  # i ile i+1 arası kesim
    segmentler: list[list[int]] = []
    bas = 0
    for s in sinirlar:
        segmentler.append(list(range(bas, s + 1)))
        bas = s + 1
    segmentler.append(list(range(bas, n)))
    return [g for g in segmentler if g]


def etiketler_uret(segmentler: list[list[int]], n: int) -> list[int]:
    """Segment grupları → birim-başına segment-id etiketi (eval metrikleri için)."""
    et = [0] * n
    for sid, grup in enumerate(segmentler):
        for i in grup:
            if 0 <= i < n:
                et[i] = sid
    return et


def _kanonik(etiket: list[int]) -> list[int]:
    """Etiketleri RUN-bazlı bitişik id'lere çevir (sınırda artan): tekrar-kullanılan
    segment-id'leri (golden ref=[0,0,1,1,0,0] gibi) Pk'nın yanlış 'aynı-segment' saymasını
    önler → [0,0,1,1,2,2]. Sınır yapısı korunur, eşitlik-tabanlı üyelik doğru olur."""
    if not etiket:
        return []
    yeni = [0]
    for i in range(1, len(etiket)):
        yeni.append(yeni[-1] + (1 if etiket[i] != etiket[i - 1] else 0))
    return yeni


def _pencere_k(etiket: list[int]) -> int:
    n = len(etiket)
    seg_sayisi = len(set(etiket)) or 1
    return max(1, round(n / (2 * seg_sayisi)))


def pk(referans: list[int], tahmin: list[int], k: int | None = None) -> float:
    """Pk: kayan k-pencere; iki uç ref'te aynı-segment mi, tahmin aynı kararı mı veriyor
    — uyumsuzluk oranı. Düşük=iyi. Etiket = birim-başına segment-id.

    Uzunluk uyumsuzluğu YAPISAL bir veri/kod hatasıdır (off-by-one, kırpılmış tahmin) →
    sessizce 1.0 dönüp kök-nedeni gizlemek yerine ValueError (review MED: kök-neden maskeleme)."""
    n = len(referans)
    if n < 2:
        return 0.0
    if len(tahmin) != n:
        raise ValueError(f"pk: referans ({n}) ile tahmin ({len(tahmin)}) uzunlukları farklı")
    ref, hyp = _kanonik(referans), _kanonik(tahmin)
    kk = min(k if k is not None else _pencere_k(ref), n - 1)
    hata = toplam = 0
    for i in range(n - kk):
        if (ref[i] == ref[i + kk]) != (hyp[i] == hyp[i + kk]):
            hata += 1
        toplam += 1
    return hata / toplam if toplam else 0.0


def _sinir_sayisi(etiket: list[int], i: int, j: int) -> int:
    return sum(1 for t in range(i, j) if etiket[t] != etiket[t + 1])


def windowdiff(referans: list[int], tahmin: list[int], k: int | None = None) -> float:
    """WindowDiff: pencere içindeki sınır SAYISI farkını cezalandırır (Pk yakın-kaçırma
    yanlılığını düzeltir). Düşük=iyi. Uzunluk uyumsuzluğu → ValueError (pk ile tutarlı)."""
    n = len(referans)
    if n < 2:
        return 0.0
    if len(tahmin) != n:
        raise ValueError(
            f"windowdiff: referans ({n}) ile tahmin ({len(tahmin)}) uzunlukları farklı"
        )
    ref, hyp = _kanonik(referans), _kanonik(tahmin)
    kk = min(k if k is not None else _pencere_k(ref), n - 1)
    hata = toplam = 0
    for i in range(n - kk):
        if _sinir_sayisi(ref, i, i + kk) != _sinir_sayisi(hyp, i, i + kk):
            hata += 1
        toplam += 1
    return hata / toplam if toplam else 0.0

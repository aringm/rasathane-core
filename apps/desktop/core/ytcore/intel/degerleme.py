from __future__ import annotations

import math
from datetime import date

from ytcore.infra.embedding import EmbeddingProvider
from ytcore.infra.index import IndexStore
from ytcore.models import DegerlemeFaktorleri, IndexKaydi

# Her faktör (novelty/rarity/nis/recency/length) 0-100; ağırlıklar config'ten.
_HALF_LIFE_GUN = 90.0
_LENGTH_CAP_KAR = 20000  # log-normalize referansı


def _recency(yayin_tarihi: str | None) -> float | None:
    """90-gün half-life exp decay (0-100). Tarih yok/geçersiz → None (sahte skor değil)."""
    if not yayin_tarihi:
        return None
    try:
        yas = (date.today() - date.fromisoformat(yayin_tarihi[:10])).days
    except ValueError:
        return None
    yas = max(0, yas)
    return float(round(100.0 * (0.5 ** (yas / _HALF_LIFE_GUN)), 1))


def _length(govde: str) -> float:
    """İçerik uzunluğu log-normalize (0-100, cap ~20K karakter)."""
    n = len(govde.strip())
    if n <= 0:
        return 0.0
    return round(min(100.0, 100.0 * math.log1p(n) / math.log1p(_LENGTH_CAP_KAR)), 1)


def bilgi_degeri(
    kayit: IndexKaydi,
    govde: str,
    embed: EmbeddingProvider,
    index: IndexStore,
    *,
    agirliklar: dict[str, float] | None = None,
) -> tuple[float, DegerlemeFaktorleri]:
    """5-faktör BilgiDeğeri (0-100), şeffaf. index korpusunu KENDİSİ HARİÇ okur.

    Novelty .35 = 1−en_yakın_benzerlik (yeni mi?); Rarity .25 = keyword ort. IDF;
    Niş .20 = 1−ort_top-K_benzerlik (kalabalık konu mu?); Recency .15 = 90-gün
    half-life; Length .05 = log-normalize. Soğuk-başlangıç graceful (korpus boş →
    novelty 100, rarity/niş 50 nötr; sahte 0 değil — boş≠başarı).
    """
    if agirliklar is None:
        from ytcore.config import get_config

        agirliklar = get_config().degerleme_agirliklari

    vektor = embed.embed([govde])[0] if govde.strip() else None
    n_korpus = index.belge_sayisi()
    komsu = index.komsular(vektor, k=10, haric_id=kayit.video_id) if vektor else []

    if not komsu:  # korpus boş / yalnız self → soğuk-başlangıç (nötr-yüksek)
        novelty: float = 100.0
        nis: float = 50.0
    else:
        novelty = round(min(100.0, max(0.0, 100.0 * (1.0 - max(komsu)))), 1)
        nis = round(min(100.0, max(0.0, 100.0 * (1.0 - (sum(komsu) / len(komsu))))), 1)

    # Rarity: doc keyword'lerinin ortalama IDF'i (FTS5 df). Korpus boş → 50 nötr.
    if n_korpus <= 0 or not kayit.keywords:
        rarity: float = 50.0
    else:
        idfler = [math.log((n_korpus + 1) / (index.terim_df(kw) + 1)) for kw in kayit.keywords[:15]]
        ham = sum(idfler) / len(idfler) if idfler else 0.0
        ust = math.log(n_korpus + 1) or 1.0  # log((N+1)/1) üst sınır
        rarity = round(min(100.0, max(0.0, 100.0 * ham / ust)), 1)

    recency = _recency(kayit.yayin_tarihi)
    length = _length(govde)

    fakt = DegerlemeFaktorleri(
        novelty=novelty, rarity=rarity, nis=nis, recency=recency, length=length
    )
    # Ağırlıklı toplam; recency None ise o ağırlığı nötr 50 say (puan sürer, boş≠başarı).
    deger = {
        "novelty": novelty,
        "rarity": rarity,
        "nis": nis,
        "recency": recency if recency is not None else 50.0,
        "length": length,
    }
    # deger.get (eksik anahtar KeyError yerine 0) + 0-100 clamp (ağırlık toplamı!=1 ya da
    # özel ağırlık geçilirse puan sınır dışına çıkmasın — review LOW; public API güvenliği).
    ham = sum(agirliklar[k] * deger.get(k, 0.0) for k in agirliklar)
    puan = round(min(100.0, max(0.0, ham)), 1)
    return puan, fakt

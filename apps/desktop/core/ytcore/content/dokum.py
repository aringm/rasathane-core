from __future__ import annotations

from dataclasses import dataclass, field

from ytcore.content.keyword import keyword_cikar
from ytcore.content.llm import LLMClient
from ytcore.content.segment import cumlelere_bol, segmentle
from ytcore.errors import KOD_HATALARI
from ytcore.infra.embedding import EmbeddingProvider

_BASLIK_SISTEM = (
    "Bu transkript bölümü için 3-5 kelimelik kısa, açıklayıcı Türkçe başlık üret. "
    "Yalnız başlığı döndür; tırnak/noktalama/açıklama ekleme. (başlık)"
)


@dataclass
class DokumBolum:
    baslangic_sn: int | None
    baslik: str
    metin: str
    keywords: list[str] = field(default_factory=list)


def baslik_uret(keywords: list[str], cumleler: list[str]) -> str:
    """Deterministik başlık fallback: en güçlü keyword'den; yoksa ilk cümlenin baş kısmından."""
    if keywords:
        return keywords[0].strip().title()
    if cumleler:
        ilk = cumleler[0].strip().rstrip(".!?…")
        return (ilk[:50] + "…") if len(ilk) > 50 else (ilk or "Bölüm")
    return "Bölüm"


def baslik_uret_llm(
    seg_metin: str,
    llm: LLMClient,
    keywords: list[str],
    cumleler: list[str],
    model: str | None = None,
) -> str:
    """LLM ile profesyonel TR bölüm başlığı (kullanıcı-yönelik kalite). Boş/aşırı uzun
    çıktıda deterministik baslik_uret fallback (model/ağ ham hata sınırda guard'lı)."""
    try:
        ham = llm.uret(_BASLIK_SISTEM, seg_metin[:1500], model=model).strip().strip("\"'").strip()
    except KOD_HATALARI:
        raise  # gerçek kod hatası (non-str dönüş vb.) maskelenmez — node.py deseniyle tutarlı
    except Exception:  # noqa: BLE001 — model/ağ ham hata; başlık best-effort, fallback'e düş
        ham = ""
    # LLM bazen cümle döndürür → ilk satır + makul uzunluk guard.
    ham = ham.splitlines()[0].strip() if ham else ""
    if ham and 2 <= len(ham) <= 80:
        return ham
    return baslik_uret(keywords, cumleler)


def dokum_derle(
    metin: str,
    embed: EmbeddingProvider,
    *,
    segment_sn: list[int] | None = None,
    llm: LLMClient | None = None,
    model: str | None = None,
) -> list[DokumBolum]:
    """Metni segmentle → her segment için keyword (MMR ile merkezi terimler) + başlık
    (llm verilirse LLM, yoksa deterministik) + timestamp (varsa).

    segment_sn = cümle-başına başlangıç saniyesi (timed transkript); None → timestamp yok.
    Boş metin → [] (boş döküm 'başarı' verme — node guard'lar).
    """
    cumleler = cumlelere_bol(metin)
    if not cumleler:
        return []
    segmentler = segmentle(cumleler, embed)
    bolumler: list[DokumBolum] = []
    for grup in segmentler:
        seg_cumleler = [cumleler[i] for i in grup]
        seg_metin = " ".join(seg_cumleler)
        # MMR (embed) ile merkezi terimleri öne al — dolgu bigram'lar yerine hukuk terimleri
        # (A03-doğrulama: konuşmalı TR'de YAKE dolgu seçebilir → bge-m3 merkezilikle düzelt).
        kws = keyword_cikar(seg_metin, ust_n=5, embed=embed)
        if llm is not None:
            baslik = baslik_uret_llm(seg_metin, llm, kws, seg_cumleler, model=model)
        else:
            baslik = baslik_uret(kws, seg_cumleler)
        sn: int | None = None
        if segment_sn and grup:
            ilk_idx = grup[0]
            if 0 <= ilk_idx < len(segment_sn):
                sn = segment_sn[ilk_idx]
        bolumler.append(DokumBolum(baslangic_sn=sn, baslik=baslik, metin=seg_metin, keywords=kws))
    return bolumler

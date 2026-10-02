from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class Metrik:
    ad: str
    aciklama: str
    hesapla: Callable[..., float]


def _ni(*a: Any, **k: Any) -> float:
    raise NotImplementedError("TR-kalite metriği Faz 1+ (held-out eval ile kalibre)")


def retrieval_recall_hesapla(
    golden: dict[str, set[str]], siralamalar: dict[str, list[str]], k: int = 10
) -> dict[str, float]:
    """recall@k + nDCG@k (golden relevance vs üretilen sıralama). bge-m3 vs qwen3-emb A/B.

    Ayırt-edici: ilgili belge üstte değilse düşük skor (kötü retrieval cezalanır —
    totoloji DEĞİL; Faz 2 pk_self dersi). Eşik kilidi held-out TR korpus bekler.
    """
    import math

    recaller: list[float] = []
    ndcgler: list[float] = []
    for q, ilgili in golden.items():
        sira = siralamalar.get(q, [])[:k]
        if not ilgili:
            continue
        bulunan = sum(1 for d in sira if d in ilgili)
        recaller.append(bulunan / len(ilgili))
        dcg = sum(1.0 / math.log2(i + 2) for i, d in enumerate(sira) if d in ilgili)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(ilgili), k)))
        ndcgler.append(dcg / idcg if idcg else 0.0)
    return {
        "recall": round(sum(recaller) / len(recaller), 4) if recaller else 0.0,
        "ndcg": round(sum(ndcgler) / len(ndcgler), 4) if ndcgler else 0.0,
    }


def _retrieval_recall_skor(
    golden: dict[str, set[str]], siralamalar: dict[str, list[str]], k: int = 10
) -> float:
    """Metrik.hesapla için birincil float (recall@k)."""
    return retrieval_recall_hesapla(golden, siralamalar, k)["recall"]


def segmentasyon_metrik(referans: list[int], tahmin: list[int]) -> dict[str, float]:
    """Pk + WindowDiff (saf-python, content.segment'ten). Düşük=iyi. Etiket = birim-başına
    segment-id (content.segment.etiketler_uret). TR eşik korpus gelince kilitlenir."""
    from ytcore.content.segment import pk, windowdiff

    return {"pk": pk(referans, tahmin), "windowdiff": windowdiff(referans, tahmin)}


def keyword_metrik(tahmin: list[str], golden: list[str]) -> dict[str, float]:
    """Set-tabanlı P/R/F1 (content.keyword'den). Golden boş → F1=0."""
    from ytcore.content.keyword import keyword_f1

    return keyword_f1(tahmin, golden)


def faithfulness_metrik(ozet: str, kaynak: str, llm: Any) -> dict[str, object]:
    """LLM-judge entailment faithfulness (content.faithfulness'tan). llm = LLMClient
    (gerçek Ollama judge ya da fake). Eşik TR-hukuk korpusla kalibre edilir."""
    from ytcore.content.faithfulness import faithfulness

    skor, durum = faithfulness(ozet, kaynak, llm)
    return {"skor": skor, "durum": durum}


def _faithfulness_skor(ozet: str, kaynak: str, llm: Any) -> float:
    """Metrik.hesapla için birincil float (skor) — dict[str,object] tip-erozyonundan kaçın."""
    from ytcore.content.faithfulness import faithfulness

    skor, _ = faithfulness(ozet, kaynak, llm)
    return skor


# TR kalite metrik iface'leri — Faz 2'de GERÇEKLENDİ. Metrik.hesapla birincil float
# döndürür (pk/f1/skor); zengin dict için segmentasyon_metrik/keyword_metrik/faithfulness_metrik.
# Eşik kalibrasyonu held-out TR korpus gelince (eval/real_docs/); makine sentetikle kurulu.
SEGMENTASYON_PK = Metrik(
    "segmentasyon_pk",
    "Embedding segmentasyon Pk/WindowDiff (TR)",
    lambda referans, tahmin: segmentasyon_metrik(referans, tahmin)["pk"],
)
KEYWORD_F1 = Metrik(
    "keyword_f1",
    "YAKE F1 (konuşmalı TR)",
    lambda tahmin, golden: keyword_metrik(tahmin, golden)["f1"],
)
OZET_FAITHFULNESS = Metrik(
    "ozet_faithfulness",
    "LLM-judge entailment (TR-hukuk kalibre)",
    _faithfulness_skor,
)
# Faz 3 — embedding retrieval (BGE-M3 vs qwen3-emb). GERÇEKLENDİ (recall@K birincil float);
# zengin recall+nDCG için retrieval_recall_hesapla. Eşik kilidi held-out TR korpus bekler.
RETRIEVAL_RECALL = Metrik(
    "retrieval_recall", "BGE-M3 vs qwen3-emb recall@K/nDCG", _retrieval_recall_skor
)
# Faz 1 transcript WER — gerçek TR korpus gelince kalibre (hedef %12-25 gerçek-dünya bandı;
# LibriSpeech %1.9 studio-clean YANILTICI). Şimdilik NotImplemented (sözleşme sabit).
TRANSCRIPT_WER = Metrik("transcript_wer", "faster-whisper TR WER (hedef %12-25)", _ni)


def mindmap_kapsam(dugum_etiketleri: list[str], ozet: str) -> float:
    """Zihin haritası kapsamı (0-1): düğüm etiketleri özetin anahtar-token'larını ne kadar
    kapsıyor (saf-python token-overlap). <2 düğüm → 0 (anlamlı ağaç değil; boş≠başarı).
    Ayırt-edici: ilgili-ağaç skoru > alakasız-ağaç (TTS = öznel A/B, oto-metrik dürüstçe yok)."""
    if len(dugum_etiketleri) < 2:
        return 0.0
    ozet_tokenlar = {t for t in ozet.lower().split() if len(t) > 3}
    if not ozet_tokenlar:
        return 0.0
    dugum_tokenlar = {t for e in dugum_etiketleri for t in e.lower().split() if len(t) > 3}
    if not dugum_tokenlar:
        return 0.0
    kesisim = ozet_tokenlar & dugum_tokenlar
    return round(len(kesisim) / len(ozet_tokenlar), 3)


# Faz 4 — zihin haritası kapsamı (yapısal eval moat). Ayırt-edici (ilgili>alakasız; totoloji
# yok). TTS kalite = öznel A/B insan (oto-metrik YOK — dürüstlük). Eşik kilidi korpus bekler.
MINDMAP_KAPSAM = Metrik(
    "mindmap_kapsam", "Zihin haritası özet-kapsamı (token-overlap, ayırt-edici)", mindmap_kapsam
)


def structural_metrik(klasor_var: bool, index_gecerli: bool) -> dict[str, bool]:
    """Faz 0 ölçülebilir metrik: stub akış doğru klasör + geçerli index üretti mi?"""
    return {
        "gecti": bool(klasor_var and index_gecerli),
        "klasor_var": klasor_var,
        "index_gecerli": index_gecerli,
    }


def transcript_metrik(transkript_var: bool, metin_uzunluk: int, durum: str) -> dict[str, object]:
    """Faz 1 ölçülebilir: 01_transcript dosyası var + boş değil + durum altyazi/asr.

    Gerçek WER (TRANSCRIPT_WER) sahip TR korpusu eval/real_docs/'a koyunca kalibre edilir.
    """
    gecti = bool(transkript_var and metin_uzunluk > 0 and durum in ("altyazi", "asr"))
    return {
        "gecti": gecti,
        "transkript_var": transkript_var,
        "metin_uzunluk": metin_uzunluk,
        "durum": durum,
    }

from __future__ import annotations

from typing import Any

from ytcore.config import get_config
from ytcore.content.ceviri import cevir, ceviri_gerekli_mi
from ytcore.content.dokum import dokum_derle
from ytcore.content.faithfulness import faithfulness
from ytcore.content.glossary import glossary_few_shot, varsayilan_glossary
from ytcore.content.llm import llm_al
from ytcore.content.ozet import ozetle
from ytcore.content.segment import cumlelere_bol
from ytcore.errors import KOD_HATALARI as _KOD_HATALARI
from ytcore.infra.embedding import embedding_al
from ytcore.obs.tracer import span_baslat
from ytcore.pipeline.state import GState


def temizle_node(state: GState) -> GState:
    """Ham içeriği kaynağa uygun biçimde temizle; orijinal dilde.

    transkript_metni'ni TEMİZ metinle günceller → downstream (pii_gate/çeviri/döküm/özet)
    temiz metni kullanır + 01_transcript_orijinal.md temiz yazılır. Yalnız gerçek edinim
    (altyazi/asr) yolunda çalışır. best-effort: kod-bug görünür çöker, ham hata → ham metni koru.
    """
    from ytcore.content.temizle import temizle_kaynak, temizle_youtube

    metin = state.get("transkript_metni", "") or ""
    durum = state.get("transkript_durumu", "")
    with span_baslat("temizle", {"durum": durum}):
        if not metin.strip() or durum not in ("altyazi", "asr", "kaynak"):
            return {}  # içerik yok / edinilemedi → dokunma
        if durum == "kaynak":
            temiz = temizle_kaynak(metin)
            return {"transkript_metni": temiz} if temiz.strip() else {}
        cfg = get_config()
        try:
            temiz = temizle_youtube(metin, llm_al(cfg.ollama_map_model), model=cfg.ollama_map_model)
        except _KOD_HATALARI:
            raise  # gerçek kod hatası — görünür çök (Faz 1 dersi)
        except Exception:  # noqa: BLE001 — temizlik best-effort; ham metni KORU (içerik kaybetme)
            return {}
        return {"transkript_metni": temiz} if temiz.strip() else {}


def ceviri_node(state: GState) -> GState:
    """Kaynak TR → atla (icerik_tr=transkript). EN → çevir. Boş içerik → icerik_yok.
    Boş/hatalı çeviri → durum=hata + icerik_tr=transkript fallback (sessiz boş YOK)."""
    metin = state.get("transkript_metni", "") or ""
    dil = state.get("transkript_kaynak_dil")
    with span_baslat("ceviri", {"kaynak_dil": str(dil)}):
        if not metin.strip():
            return {"icerik_tr": "", "ceviri_durumu": "icerik_yok"}
        if not ceviri_gerekli_mi(dil):
            return {"icerik_tr": metin, "ceviri_durumu": "atlandi"}
        cfg = get_config()
        llm = llm_al(cfg.ollama_ceviri_model)
        gloss = glossary_few_shot(varsayilan_glossary())
        try:
            tr = cevir(metin, llm, glossary_metni=gloss, model=cfg.ollama_ceviri_model)
        except _KOD_HATALARI:
            raise  # gerçek kod hatası — görünür çök (Faz 1 dersi)
        except Exception as e:  # noqa: BLE001 — model/ağ ham hata sınırda graceful
            # Çeviri GEREKLIYDI ama başarısız → icerik_tr="" (cevrilmemiş yabancı metinden
            # döküm/özet ÜRETME — dil-karışık yanıltıcı "başarı" yok, boş≠başarı/hata-yüzeyde).
            return {"icerik_tr": "", "ceviri_durumu": "hata", "ceviri_hata": str(e)[:300]}
        return {"icerik_tr": tr, "ceviri_durumu": "cevrildi"}


def _segment_sn_haritasi(metin: str, timed: list[dict[str, Any]]) -> list[int] | None:
    """Timed VTT segmentlerini cümle-başına saniyeye kaba (orantısal) eşle (best-effort)."""
    if not timed:
        return None
    cumleler = cumlelere_bol(metin)
    if not cumleler:
        return None
    sns = [int(t.get("baslangic_sn", 0)) for t in timed]
    if not sns:
        return None
    n = len(cumleler)
    return [sns[min(len(sns) - 1, int((idx / n) * len(sns)))] for idx in range(n)]


def dokum_node(state: GState) -> GState:
    """icerik_tr → segmentle + keyword (MMR) + LLM-başlıklı kronolojik döküm (+timestamp).

    YALNIZ icerik_tr (kanonik çalışma Türkçesi) kullanılır — transkript_metni fallback YOK:
    çeviri 'hata' iken icerik_tr='' olur ve döküm atlanır (cevrilmemiş yabancı metinden üretme).
    """
    metin = state.get("icerik_tr", "") or ""
    timed = state.get("transkript_segmentler") or []
    with span_baslat("dokum", {}):
        if not metin.strip():
            return {"dokum_bolumler": [], "dokum_segment_sayisi": 0, "keywords": []}
        cfg = get_config()
        segment_sn = _segment_sn_haritasi(metin, timed)
        embed = embedding_al()
        llm = llm_al(cfg.ollama_map_model)  # başlık üretimi (hafif görev → map modeli)
        bolumler = dokum_derle(
            metin, embed, segment_sn=segment_sn, llm=llm, model=cfg.ollama_map_model
        )
    keywords: list[str] = []
    for b in bolumler:
        for k in b.keywords:
            if k not in keywords:
                keywords.append(k)
    return {
        "dokum_bolumler": [
            {
                "baslangic_sn": b.baslangic_sn,
                "baslik": b.baslik,
                "metin": b.metin,
                "keywords": b.keywords,
            }
            for b in bolumler
        ],
        "dokum_segment_sayisi": len(bolumler),
        "keywords": keywords[:20],
    }


def ozet_node(state: GState) -> GState:
    """icerik_tr → map-reduce özet + faithfulness. Eşik-altı → 1x yeniden-dene (en iyiyi tut).

    YALNIZ icerik_tr — transkript_metni fallback YOK (çeviri hata → icerik_tr='' → özet atlanır;
    cevrilmemiş yabancı metni özetleyip 'başarı' sayma).
    """
    metin = state.get("icerik_tr", "") or ""
    cfg = get_config()
    bos = {"kisa": "", "orta": "", "detay": ""}
    with span_baslat("ozet", {}):
        if not metin.strip():
            return {
                "ozet": bos,
                "ozet_faithfulness": None,
                "ozet_faithfulness_durum": "ozet_yok",
            }
        llm = llm_al(cfg.ollama_reduce_model)
        embed = embedding_al()
        try:
            sonuc = ozetle(
                metin,
                llm,
                embed,
                map_model=cfg.ollama_map_model,
                reduce_model=cfg.ollama_reduce_model,
            )
        except _KOD_HATALARI:
            raise
        except Exception as e:  # noqa: BLE001 — model/ağ ham hata sınırda graceful
            return {
                "ozet": bos,
                "ozet_faithfulness": None,
                "ozet_faithfulness_durum": "hata",
                "ozet_hata": str(e)[:300],
            }
        judge = llm_al(cfg.ollama_judge_model)
        # embed → uzun kaynakta iddia-başına ilgili-chunk seçimi (naif [:6000] kesimi yok, #11)
        skor, durum = faithfulness(
            sonuc["detay"], metin, judge, model=cfg.ollama_judge_model, embed=embed
        )
        if durum == "esik_alti":
            try:
                sonuc2 = ozetle(
                    metin,
                    llm,
                    embed,
                    map_model=cfg.ollama_map_model,
                    reduce_model=cfg.ollama_reduce_model,
                )
                skor2, durum2 = faithfulness(
                    sonuc2["detay"], metin, judge, model=cfg.ollama_judge_model, embed=embed
                )
                if skor2 >= skor:  # en iyiyi tut
                    sonuc, skor = sonuc2, skor2
                    durum = "yeniden_uretildi" if durum2 == "gecti" else durum2
            except _KOD_HATALARI:
                raise  # gerçek kod hatası retry yolunda da maskelenmez (ana yolla tutarlı)
            except Exception:  # noqa: BLE001 — yeniden-dene best-effort; ilk sonucu koru
                pass
        return {"ozet": sonuc, "ozet_faithfulness": skor, "ozet_faithfulness_durum": durum}

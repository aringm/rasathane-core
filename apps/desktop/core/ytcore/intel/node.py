from __future__ import annotations

from ytcore.config import get_config
from ytcore.content.llm import llm_al
from ytcore.content.resmi import SKIP_REASON, SKIP_STATUS, resmi_belge
from ytcore.errors import KOD_HATALARI as _KOD_HATALARI
from ytcore.infra.embedding import embedding_al
from ytcore.infra.index import index_al
from ytcore.intel.degerleme import bilgi_degeri
from ytcore.intel.factcheck import fact_check
from ytcore.intel.kisisel import kisisel_analiz
from ytcore.intel.memory import memory_al
from ytcore.intel.websearch import websearch_al
from ytcore.models import IndexKaydi
from ytcore.obs.tracer import span_baslat
from ytcore.pipeline.state import GState


def _govde(state: GState) -> str:
    """Değerleme/kişisel/fact-check için kanonik gövde: özet detay > içerik_tr."""
    ozet = state.get("ozet") or {}
    return (ozet.get("detay") or "").strip() or (state.get("icerik_tr") or "").strip()


def degerleme_node(state: GState) -> GState:
    govde = _govde(state)
    with span_baslat("degerleme", {}):
        if not govde:
            # İçerik yok (review tur-2 MED): kisisel/factcheck ile tutarlı durum izi —
            # 'icerik_yok' (govde boş) model/IO 'hata'sından AYRI (ikisi de puan=None idi).
            return {
                "degerleme_puani": None,
                "degerleme_durum": "icerik_yok",
                "degerleme_faktorleri": {},
                "govde_index": "",
            }
        kayit = IndexKaydi.model_validate(state["metadata"])
        kayit = kayit.model_copy(update={"keywords": state.get("keywords") or []})
        embed = embedding_al()
        index = index_al()
        try:
            puan, fakt = bilgi_degeri(kayit, govde, embed, index)
        except _KOD_HATALARI:
            raise  # gerçek kod hatası — görünür çök (Faz 1/2 dersi)
        except Exception as e:  # noqa: BLE001 — embed/index ham hata sınırda graceful
            # Kök-neden yüzeyde (kisisel/factcheck deseni) — sessiz değil; puan None ama
            # 'hata' durumu + degerleme_hata 'icerik_yok'tan ayırt edilir (boş≠başarı).
            return {
                "degerleme_puani": None,
                "degerleme_durum": "hata",
                "degerleme_hata": str(e)[:300],
                "degerleme_faktorleri": {},
                "govde_index": govde,
            }
    return {
        "degerleme_puani": puan,
        "degerleme_durum": "uretildi",
        "degerleme_faktorleri": fakt.model_dump(),
        "govde_index": govde,
    }


def kisisel_node(state: GState) -> GState:
    if resmi := resmi_belge(state):
        return {
            "kisisel_durum": SKIP_STATUS,
            "kisisel_analiz": (
                "Bu resmî düzenleme için kişisel hukuki yorum otomatik üretilmedi. "
                "Kaynak alıntıları MADDE/fıkra yapısını korur. Değişikliğin asıl mevzuata "
                "uygulanması için bağlı ekler ve güncel konsolide metin ayrıca incelenmelidir."
                f"\n\nResmî kaynak: {resmi.url}"
            ),
        }
    govde = _govde(state)
    with span_baslat("kisisel", {}):
        if not govde:
            return {"kisisel_analiz": "", "kisisel_durum": "icerik_yok"}
        cfg = get_config()
        llm = llm_al(cfg.ollama_memory_model)
        bellek = memory_al()
        try:
            analiz, durum = kisisel_analiz(
                govde,
                llm,
                bellek,
                kullanici_base=cfg.kullanici_base,
                model=cfg.ollama_memory_model,
                kaynak_turu=state.get("kaynak_turu"),
            )
        except _KOD_HATALARI:
            raise
        except Exception as e:  # noqa: BLE001 — model/IO ham hata sınırda graceful
            return {"kisisel_analiz": "", "kisisel_durum": "hata", "kisisel_hata": str(e)[:300]}
    return {"kisisel_analiz": analiz, "kisisel_durum": durum}


def factcheck_node(state: GState) -> GState:
    if resmi_belge(state):
        return {
            "factcheck_iddialar": [],
            "factcheck_durum": SKIP_STATUS,
            "factcheck_reason": SKIP_REASON,
        }
    import os

    from ytcore.router.ner import ner_al

    govde = _govde(state)
    with span_baslat("factcheck", {}):
        if not govde:
            return {"factcheck_iddialar": [], "factcheck_durum": "icerik_yok"}
        cfg = get_config()
        llm = llm_al(cfg.ollama_verdict_model)
        web = websearch_al()
        # Faz 5 NER: yalnız web-egress gerçekten mümkünken (anahtar/fixture) — anahtarsız
        # kurulumda subprocess hiç spawn olmaz (performans + Faz 4 davranışı birebir).
        # NOT (review tur-1): tavily_api_key SAYILMAZ — Tavily client'ı yok (websearch_al
        # yalnız Serper kurar); tek başına Tavily anahtarı web'i aktive etmez.
        # Faz 7: searxng_url da egress-mümkün kılar → NER gate (çıplak ad-soyad) egress'ten
        # ÖNCE her zaman geçsin. SearXNG opt-in olduğu için ner=None deliği yok (web_mumkun
        # ⇔ websearch_al gerçek egress sağlayıcı döndürür).
        web_mumkun = bool(
            cfg.serper_api_key
            or cfg.searxng_url
            or cfg.firecrawl_url
            or os.environ.get("YT_WEBSEARCH_FIXTURE")
        )
        ner = ner_al() if web_mumkun else None
        # Faz 5 Mod B: cloud verdict YALNIZ hedef=cloud (PII-temiz COMPLEX) + bilinçli opt-in
        # (YT_CLOUD_VERDICT=1) + anahtar varken. Aksi bugünkü local qwen (Faz 3 davranışı AYNEN).
        cloud = None
        if state.get("hedef") == "cloud" and cfg.cloud_verdict_acik and cfg.anthropic_api_key:
            from ytcore.router.cloud_client import CloudClient

            cloud = CloudClient(cfg.anthropic_api_key)
        try:
            iddialar, durum = fact_check(
                govde,
                llm,
                web,
                model=cfg.ollama_verdict_model,
                ner=ner,
                cloud=cloud,
                web_mumkun=web_mumkun,
            )
        except _KOD_HATALARI:
            raise
        except Exception as e:  # noqa: BLE001 — model/web ham hata sınırda graceful
            return {
                "factcheck_iddialar": [],
                "factcheck_durum": "hata",
                "factcheck_hata": str(e)[:300],
            }
    cikti: GState = {"factcheck_iddialar": iddialar, "factcheck_durum": durum}
    if cloud is not None:
        # Maliyet/0-cloud takibi (A14): yalnız GERÇEK çağrılar sayaca işlenir.
        cikti["cloud_cagrisi_sayisi"] = (
            int(state.get("cloud_cagrisi_sayisi", 0)) + cloud.cagri_sayisi
        )
        cikti["cloud_girdi_token"] = (
            int(state.get("cloud_girdi_token", 0)) + cloud.toplam_girdi_token
        )
        cikti["cloud_cikti_token"] = (
            int(state.get("cloud_cikti_token", 0)) + cloud.toplam_cikti_token
        )
    return cikti

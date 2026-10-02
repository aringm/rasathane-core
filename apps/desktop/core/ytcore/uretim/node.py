from __future__ import annotations

from pathlib import Path

from ytcore.config import get_config
from ytcore.content.llm import llm_al
from ytcore.errors import KOD_HATALARI as _KOD_HATALARI
from ytcore.obs.tracer import span_baslat
from ytcore.pipeline.state import GState


def _govde(state: GState) -> str:
    ozet = state.get("ozet") or {}
    return (ozet.get("detay") or "").strip() or (state.get("icerik_tr") or "").strip()


def _ozet_metni(state: GState) -> str:
    ozet = state.get("ozet") or {}
    return (ozet.get("detay") or ozet.get("kisa") or "").strip()


def _sonuc_patch(state: GState, **alanlar: object) -> dict[str, object]:
    return {**(state.get("sonuc") or {}), **alanlar}


def harita_node(state: GState) -> GState:
    from ytcore.uretim.harita import agac_to_markmap, dugum_say, harita_agaci
    from ytcore.uretim.markmap import markmap_html

    govde = _govde(state)
    with span_baslat("harita", {}):
        if not govde:
            return {
                "harita_durum": "icerik_yok",
                "harita_dugum_sayisi": 0,
                "sonuc": _sonuc_patch(state, harita_durum="icerik_yok"),
            }
        cfg = get_config()
        meta = state.get("metadata") or {}
        klasor = Path(state["klasor"])
        try:
            agac = harita_agaci(govde, llm_al(cfg.harita_model), model=cfg.harita_model)
            n = dugum_say(agac)
            if n <= 1:  # graceful tek-düğüm = anlamlı ağaç üretilemedi (boş≠başarı)
                return {
                    "harita_durum": "icerik_yok",
                    "harita_dugum_sayisi": n,
                    "sonuc": _sonuc_patch(state, harita_durum="icerik_yok", harita_dugum_sayisi=n),
                }
            zaman_url = (
                str(meta.get("video_url", ""))
                if meta.get("kaynak_turu", "youtube") == "youtube"
                else ""
            )
            veri = agac_to_markmap(agac, video_url=zaman_url)
            html = markmap_html(veri, baslik=str(meta.get("baslik", "Zihin Haritası")))
            (klasor / "05_zihin-haritasi.html").write_text(html, encoding="utf-8")
        except _KOD_HATALARI:
            raise  # gerçek kod hatası — görünür çök (Faz 1/2/3 dersi)
        except Exception as e:  # noqa: BLE001 — model/IO ham hata sınırda graceful
            return {
                "harita_durum": "hata",
                "harita_hata": str(e)[:300],
                "harita_dugum_sayisi": 0,
                "sonuc": _sonuc_patch(state, harita_durum="hata"),
            }
    return {
        "harita_durum": "uretildi",
        "harita_dugum_sayisi": n,
        "sonuc": _sonuc_patch(state, harita_durum="uretildi", harita_dugum_sayisi=n),
    }


def seslendirme_node(state: GState) -> GState:
    from ytcore.uretim.tts import seslendirme_karari, tts_al, tts_pii_var_mi

    metin = _ozet_metni(state)
    with span_baslat("seslendirme", {}):
        if not metin:
            return {
                "ses_durum": "icerik_yok",
                "ses_kaynak": None,
                "sonuc": _sonuc_patch(state, ses_durum="icerik_yok"),
            }
        cfg = get_config()
        klasor = Path(state["klasor"])
        # KVKK gate: tts_pii_var_mi = TEK enforcement yardımcısı (pattern + cloud-mümkünse
        # NER; MCP seslendir tool'u ile AYNI karar — kopya gate sapması yok, review tur-1).
        pii = tts_pii_var_mi(metin)
        kaynak, _gerekce = seslendirme_karari(
            pii_var=pii, cloud_acik=cfg.tts_cloud_acik, anahtar_var=bool(cfg.openai_api_key)
        )
        hedef = klasor / ("04_ozet.mp3" if kaynak == "cloud" else "04_ozet.wav")
        try:
            s = tts_al(kaynak).seslendir(metin, hedef)
        except _KOD_HATALARI:
            raise
        except Exception as e:  # noqa: BLE001 — TTS ham hata sınırda graceful
            return {
                "ses_durum": "hata",
                "ses_hata": str(e)[:300],
                "ses_kaynak": kaynak,
                "sonuc": _sonuc_patch(state, ses_durum="hata", ses_kaynak=kaynak),
            }
    return {
        "ses_durum": s.durum,
        "ses_kaynak": s.kaynak,
        "sonuc": _sonuc_patch(state, ses_durum=s.durum, ses_kaynak=s.kaynak),
    }

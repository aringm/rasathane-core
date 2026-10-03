from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph
from rasathane.sources import KaynakSinyali

from ytcore.config import get_config
from ytcore.content.resmi import MODE, SKIP_STATUS, resmi_belge
from ytcore.local.ollama_ping import ollama_erisilebilir, ollama_ping
from ytcore.models import AnalizSonucu, FactIddia, IndexKaydi
from ytcore.obs.tracer import span_baslat
from ytcore.output.klasor import analiz_klasoru_yaz
from ytcore.pipeline.state import GState
from ytcore.router.complexity import Hedef, Karmasiklik, yonlendir
from ytcore.router.pii_gate import pii_iceriyor_mu

__all__ = ["GState", "graph_olustur"]


def _kaynak_hata_kaydi(url: str, konu: str, tur: str, mesaj: str) -> IndexKaydi:
    """Edinim başarısızken de çakışmayan, yazılabilir minimal kaynak kaydı üret."""
    from ytcore.text.slug import slugify

    kisa = hashlib.sha256(url.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return IndexKaydi(
        video_url=url,
        video_id=f"{tur}:{kisa}",
        baslik=f"({tur} kaynağına erişilemedi)",
        anadil="",
        kanal="",
        konu=konu,
        uretici_slug="erisilemedi",
        video_slug=slugify(mesaj[:48], fallback=kisa),
        analiz_tarihi=date.today().isoformat(),
        kaynak_turu=tur,
        kaynak_url=url,
        kaynak_id=kisa,
        kaynak_sahibi="",
        kaynak_ozel={"edinim_hatasi": mesaj[:300]},
    )


def _kaynak_belgesi_node(url: str, konu: str) -> GState:
    """YouTube dışındaki adapter belgesini mevcut ortak pipeline state'ine köprüle."""
    from rasathane.sources import KaynakHatasi, kaynak_edin, kaynak_turu_bul

    from ytcore.text.slug import slugify

    try:
        belge = kaynak_edin(url)
    except KaynakHatasi as e:
        tur_degeri = "web"
        try:
            tur_degeri = kaynak_turu_bul(url).value
        except KaynakHatasi:
            pass
        kayit = _kaynak_hata_kaydi(url, konu, tur_degeri, e.mesaj)
        return {
            "kaynak_turu": tur_degeri,
            "kaynak_durumu": e.kod,
            "kaynak_sinyalleri": [],
            "kaynak_ozel": {"hata_kodu": e.kod},
            "transkript_metni": "",
            "transkript_durumu": "hata",
            "transkript_kaynak_dil": None,
            "transkript_hata": e.mesaj[:300],
            "transkript_segmentler": [],
            "asr_tier": None,
            "metadata": kayit.model_dump(),
        }

    sahip = belge.sahip or ""
    dogal_id = belge.kimlik.strip() or hashlib.sha256(url.encode()).hexdigest()[:12]
    source_uid = f"{belge.tur.value}:{dogal_id}"
    yayin = belge.yayin_tarihi[:10] if belge.yayin_tarihi else None
    kayit = IndexKaydi(
        video_url=belge.kanonik_url,
        video_id=source_uid,
        baslik=belge.baslik or "(başlık yok)",
        anadil=belge.dil or "",
        kanal=sahip,
        yayin_tarihi=yayin,
        sure_sn=None,
        konu=konu,
        uretici_slug=slugify(sahip, fallback=belge.tur.value),
        video_slug=slugify(belge.baslik, fallback=dogal_id)[:48],
        analiz_tarihi=date.today().isoformat(),
        kaynak_turu=belge.tur.value,
        kaynak_url=belge.kanonik_url,
        kaynak_id=dogal_id,
        kaynak_sahibi=sahip,
        kaynak_tarihi=belge.yayin_tarihi,
        kaynak_guncelleme_tarihi=belge.guncelleme_tarihi,
        kaynak_etiketleri=belge.etiketler,
        kaynak_metrikleri=belge.metrikler,
        kaynak_ozel=belge.ozel,
    )
    source_state: GState = {
        "kaynak_turu": belge.tur.value,
        "kaynak_durumu": belge.edinim_durumu,
        "kaynak_sinyalleri": [s.model_dump() for s in belge.sinyaller],
        "kaynak_ozel": belge.ozel,
        # Ortak graph bugün bu geriye uyumlu kanonik alanı tüketiyor. İçerik artık yalnız
        # transkript olmak zorunda değil; sonraki migration'da `kaynak_metni` alias'ı eklenebilir.
        "transkript_metni": belge.metin,
        "transkript_durumu": "kaynak" if belge.metin.strip() else "icerik_bos",
        "transkript_kaynak_dil": belge.dil,
        "transkript_segmentler": [],
        "asr_tier": None,
        "metadata": kayit.model_dump(),
        "analysis_mode": "model_analysis",
    }
    if resmi := resmi_belge(source_state):
        kayit = kayit.model_copy(
            update={
                "baslik": resmi.baslik,
                "kanal": resmi.sahip,
                "kaynak_sahibi": resmi.sahip,
                "yayin_tarihi": resmi.yayin_tarihi,
                "kaynak_tarihi": resmi.yayin_tarihi,
                "kaynak_ozel": {
                    **kayit.kaynak_ozel,
                    "analysis_mode": MODE,
                    "official_issue_number": resmi.sayi,
                },
            }
        )
        source_state["metadata"] = kayit.model_dump()
        source_state["analysis_mode"] = MODE
    return source_state


def _transcript_node(state: GState) -> GState:
    # Faz 1: URL türünü seç. YouTube mevcut altyazı/ASR yolunu aynen korur; diğer public
    # kaynaklar SourceAdapter → KaynakBelgesi ile ortak hatta girer.
    from rasathane.sources import KaynakHatasi, KaynakTuru, kaynak_turu_bul

    url = state.get("url", "")
    konu = state.get("konu", "genel")
    try:
        tur = kaynak_turu_bul(url)
    except KaynakHatasi:
        return _kaynak_belgesi_node(url, konu)
    if tur is not KaynakTuru.youtube:
        with span_baslat("source_acquire", {"kaynak_turu": tur.value}):
            return _kaynak_belgesi_node(url, konu)

    # YouTube: altyazı-önce temiz transkript + metadata. Altyazı yoksa & izin yoksa
    # `altyazi_yok`; sessiz Whisper fallback yok. Ağır importlar lazy kalır.
    from ytcore.transcript.asr import SubprocessASR
    from ytcore.transcript.fetcher import fetcher_al
    from ytcore.transcript.metadata import info_to_index, url_video_id
    from ytcore.transcript.node import transkript_uret

    cfg = get_config()
    fetcher = fetcher_al()
    asr = SubprocessASR(python=cfg.asr_python)
    with span_baslat("transcript", {"asr_izin": str(state.get("asr_izin", False))}):
        try:
            # YALNIZ ağ/edinim çağrıları try içinde (re-review R1: saf parse info_to_index
            # DIŞARIDA, yoksa parse-bug başarılı transkripti 'hata' gibi gösterir).
            meta = fetcher.metadata(url)
            t = transkript_uret(fetcher, url, bool(state.get("asr_izin", False)), asr)
        except (NameError, AttributeError, TypeError, ImportError, KeyError, IndexError):
            raise  # GERÇEK kod hatası — maskeleme, görünür çök (re-review R4)
        except Exception as e:  # noqa: BLE001 — ağ/erişim hatası graceful (spec §8)
            # Private/silinmiş/429/POT-gerekli → çökme YOK; net hata + minimal metadata.
            vid = url_video_id(url)
            kayit = IndexKaydi(
                video_url=url,
                video_id=vid,
                baslik="(video erişilemedi)",
                anadil="",
                kanal="",
                konu=konu,
                uretici_slug="erisilemedi",
                video_slug=vid,
                analiz_tarihi=date.today().isoformat(),
                kaynak_turu="youtube",
                kaynak_url=url,
                kaynak_id=vid,
            )
            return {
                "kaynak_turu": "youtube",
                "kaynak_durumu": "hata",
                "kaynak_sinyalleri": [],
                "kaynak_ozel": {},
                "transkript_metni": "",
                "transkript_durumu": "hata",
                "transkript_kaynak_dil": None,
                "transkript_hata": f"{type(e).__name__}: {str(e)[:300]}",
                "asr_tier": None,
                "metadata": kayit.model_dump(),
            }
    # Metadata parse (hardened → exception fırlatmaz) ve anadil backfill başarı yolunda.
    kayit = info_to_index(meta.info, konu, date.today().isoformat())
    # 'language' boşsa anadil'i YALNIZ altyazı dil kodundan doldur (güvenilir); ASR
    # whisperx dil='tr' ECHO ettiği için ASR yolundan backfill etme (re-review R6).
    if t.durum == "altyazi" and not kayit.anadil and t.kaynak_dil:
        kayit = kayit.model_copy(update={"anadil": t.kaynak_dil})
    kayit = kayit.model_copy(
        update={
            "kaynak_turu": "youtube",
            "kaynak_url": kayit.video_url or url,
            "kaynak_id": kayit.video_id,
            "kaynak_sahibi": kayit.kanal,
            "kaynak_tarihi": kayit.yayin_tarihi,
        }
    )
    edinim_etiketi = (
        "Altyazı" if t.durum == "altyazi" else "Yerel ASR" if t.durum == "asr" else "İçerik yok"
    )
    return {
        "kaynak_turu": "youtube",
        "analysis_mode": "model_analysis",
        "kaynak_durumu": t.durum,
        "kaynak_sinyalleri": [
            {
                "etiket": "Edinim",
                "deger": edinim_etiketi,
                "aciklama": "Video metni cihazda edinildi ve ortak analiz hattına aktarıldı.",
                "durum": "iyi" if t.metin.strip() else "uyari",
            },
            {
                "etiket": "Zamanlı bölüm",
                "deger": len(t.segmentler),
                "aciklama": "Kaynak içindeki zaman referansları korunur.",
                "durum": "bilgi",
            },
        ],
        "kaynak_ozel": {},
        "transkript_metni": t.metin,
        "transkript_durumu": t.durum,
        "transkript_kaynak_dil": t.kaynak_dil,
        "asr_tier": t.asr_tier,
        "transkript_segmentler": t.segmentler,
        "metadata": kayit.model_dump(),
    }


def _pii_gate_node(state: GState) -> GState:
    # Faz 1: PII-gate GERÇEK transkript metnine uygulanır (değişmez #1). Metin yoksa
    # (altyazi_yok) url'ye düşülür — yine de bir şey değerlendirilir, deny-by-default.
    metin = state.get("transkript_metni", "") or state.get("url", "")
    with span_baslat("pii_gate", {"deny_by_default": "true"}):
        r = pii_iceriyor_mu(metin)
    return {"pii_tespit": r.var}


def _router_node(state: GState) -> GState:
    from ytcore.router.complexity import siniflandir

    # YT_FORCE_COMPLEX=1 -> COMPLEX (test/dev kapısı, Faz 0'dan beri); aksi GERÇEK heuristik
    # sınıflandırma (Faz 5 — A11: saf-python <1ms; eşikler TR korpus gelince kalibre).
    force_complex = os.environ.get("YT_FORCE_COMPLEX", "0") == "1"
    metin = state.get("transkript_metni", "")
    pii = bool(state.get("pii_tespit"))
    # Analiz edilecek GERÇEK içerik yoksa (altyazi_yok/icerik_bos/hata) cloud yolunu
    # ARMING etme — local'e kısa devre (icerik yokken cloud cagrisi anlamsiz; M1).
    if not metin.strip():
        with span_baslat("router", {"pii": str(pii), "icerik": "yok"}):
            return {
                "hedef": Hedef.LOCAL.value,
                "cloud_cagrisi_sayisi": 0,
                "cloud_girdi_token": 0,
                "cloud_cikti_token": 0,
                "karmasiklik": "",
            }
    karmasiklik = Karmasiklik.COMPLEX if force_complex else siniflandir(metin[:8000])
    with span_baslat("router", {"pii": str(pii), "karmasiklik": karmasiklik.value}):
        y = yonlendir(karmasiklik, pii_var=pii, cloud_erisilebilir=True)
    # Faz 5: stub çağrısı KALKTI — cloud_cagrisi_sayisi artık yalnız GERÇEK CloudClient
    # çağrılarını sayar (dürüst 0-cloud kanıtı). Gerçek kullanım: factcheck cloud-verdict
    # (bilinçli opt-in YT_CLOUD_VERDICT=1 + anahtar + hedef=cloud — intel/node.py).
    # Token sayaçları da BURADA resetlenir (review tur-1: thread reuse'da önceki analizin
    # token'ları yeni sonuca taşınmasın — sayaç-reset emsali).
    return {
        "hedef": y.hedef.value,
        "cloud_cagrisi_sayisi": 0,
        "cloud_girdi_token": 0,
        "cloud_cikti_token": 0,
        "karmasiklik": karmasiklik.value,
    }


def _local_ping_node(state: GState) -> GState:
    # YT_OLLAMA_PING=0 -> gerçek round-trip atlanır (testler hızlı/deterministik;
    # gerçek ping kanıtı dedicated testlerde). Varsayılan açık (üretimde local yol kanıtı).
    ms: float | None = None
    if os.environ.get("YT_OLLAMA_PING", "1") != "0" and ollama_erisilebilir():
        with span_baslat("ollama_ping", {"hedef": "local"}):
            try:
                ms = ollama_ping().sure_ms
            except Exception:  # noqa: BLE001 — ping yalnız TANI (ollama_ping_ms); Ollama
                # ayakta ama chat-model yok / HTTP hatası → analizi ÇÖKERTMEMELİ. İçerik
                # node'ları (ceviri/dokum/ozet) kendi Ollama hatalarını yönetir; ping None.
                ms = None
    return {"ollama_ping_ms": ms}


def _output_node(state: GState) -> GState:
    from ytcore.content.dokum import DokumBolum
    from ytcore.infra.embedding import embedding_al
    from ytcore.infra.index import index_al
    from ytcore.intel.memory import memory_al
    from ytcore.models import DegerlemeFaktorleri
    from ytcore.output.ceviri_yaz import ceviri_yaz
    from ytcore.output.degerleme_yaz import degerleme_yaz
    from ytcore.output.dokum_yaz import dokum_yaz
    from ytcore.output.factcheck_yaz import factcheck_yaz
    from ytcore.output.kaynak_yaz import kaynak_icerigi_yaz
    from ytcore.output.kisisel_yaz import kisisel_yaz
    from ytcore.output.ozet_yaz import ozet_yaz
    from ytcore.output.sunum_yaz import sunum_yaz
    from ytcore.output.transcript_yaz import transcript_yaz

    cfg = get_config()
    kayit = IndexKaydi.model_validate(state["metadata"])
    resmi = resmi_belge(state)
    keywords = state.get("keywords") or []
    if keywords:
        kayit = kayit.model_copy(update={"keywords": keywords})
    # Faz 3: değerleme puanını kayit'e işle KLASÖR YAZIMINDAN ÖNCE (00_index.json'a girsin).
    degerleme_puani = state.get("degerleme_puani")
    degerleme_fakt = DegerlemeFaktorleri(**(state.get("degerleme_faktorleri") or {}))
    if degerleme_puani is not None:
        kayit = kayit.model_copy(
            update={"degerleme_puani": degerleme_puani, "degerleme_faktorleri": degerleme_fakt}
        )
    # Motor kökeni her analizde 00_index.json'a işlenir (kullanıcı isteği 2026-08-24):
    # hangi backend/LLM/embedding/profil — sağlık bayrakları dahil. Klasör yazımından ÖNCE.
    from ytcore.local.llamacpp import motor_raporu

    motor = motor_raporu()
    kayit = kayit.model_copy(update={"motor": motor})
    durum = state.get("transkript_durumu", "altyazi_yok")
    metin = state.get("transkript_metni", "")
    with span_baslat("output", {"durum": durum}):
        klasor = analiz_klasoru_yaz(
            kayit, cfg.output_base, output_run_id=state.get("output_run_id")
        )
        if kayit.kaynak_turu == "youtube":
            transcript_yaz(
                klasor, kayit, metin, durum, state.get("asr_tier"), state.get("transkript_hata")
            )
        else:
            kaynak_icerigi_yaz(
                klasor,
                kayit,
                metin,
                state.get("kaynak_durumu", durum),
                state.get("transkript_hata"),
            )
        # Faz 2 çıktıları — yalnız içerik üretildiyse (boş≠başarı: boş dosya yazma).
        ceviri_durumu = state.get("ceviri_durumu", "atlandi")
        if ceviri_durumu == "cevrildi" and (state.get("icerik_tr") or "").strip():
            ceviri_yaz(klasor, kayit, state["icerik_tr"])
        bolumler = [DokumBolum(**b) for b in (state.get("dokum_bolumler") or [])]
        if bolumler:
            dokum_yaz(klasor, kayit, bolumler)
        ozet = state.get("ozet") or {}
        if ozet.get("detay") or ozet.get("kisa"):
            ozet_yaz(
                klasor,
                kayit,
                ozet,
                state.get("ozet_faithfulness"),
                state.get("ozet_faithfulness_durum") or "",
            )
        # Faz 3 çıktıları (boş≠başarı: yalnız üretildiyse yaz).
        govde_index = state.get("govde_index") or ""
        if degerleme_puani is not None:
            degerleme_yaz(klasor, kayit, degerleme_puani, degerleme_fakt)
        kisisel_metni = state.get("kisisel_analiz") or ""
        if kisisel_metni.strip():
            kisisel_yaz(klasor, kayit, kisisel_metni)
        factcheck_iddialar = state.get("factcheck_iddialar") or []
        factcheck_durum = state.get("factcheck_durum", "atlandi")
        if factcheck_iddialar or factcheck_durum == SKIP_STATUS:
            factcheck_yaz(
                klasor,
                kayit,
                factcheck_iddialar,
                factcheck_durum,
                reason=state.get("factcheck_reason", ""),
            )
        # Faz 6 (#3+#5): profesyonel sunum PDF'i (özet + kişisel analiz + değerleme tek dosyada).
        # Özet üretildiyse yaz (best-effort; Typst yoksa None). md/diğer dosyalar birincil.
        # Faz 7 (review MED): sunum_yaz dönüşünü yakala → sunum_durum. Typst yoksa PDF YAZILMAZ
        # (None) → GUI sunum butonu gösterilmemeli (harita deseniyle simetri; aksi ham-JSON hata).
        sunum_durum = "atlandi"
        if ozet.get("detay") or ozet.get("kisa"):
            _sunum_p = sunum_yaz(
                klasor,
                kayit,
                ozet,
                state.get("ozet_faithfulness"),
                kisisel_metni,
                degerleme_puani,
                degerleme_fakt,
            )
            sunum_durum = "uretildi" if _sunum_p is not None else "hata"
        # Global index + bellek ekle. AYRI try blokları (review HIGH): index başarılı olup
        # bellek patlarsa index_eklendi yine True (yanıltıcı False yok).
        from ytcore.errors import KOD_HATALARI as _KOD_HATALARI

        index_eklendi = False
        bellek_eklendi = False
        if govde_index and degerleme_puani is not None:
            try:
                vektor = embedding_al().embed([govde_index])[0]
                index_al().ekle(kayit, govde_index, vektor)
                index_eklendi = True
            except _KOD_HATALARI:
                raise  # index = aranabilir korpus (semi-kritik); kod-bug görünür çök
            except Exception:  # noqa: BLE001 — index I/O ham hata sınırı (analiz kaybolmaz)
                index_eklendi = False
            # Bellek TAMAMEN best-effort (review tur-2 HIGH): yardımcı kişiselleştirme katmanı
            # (perf ~%50, öneri). Bir bellek-bug'ı 01..08 yazılmış + index eklenmiş TAMAMLANMIŞ
            # analizi ÇÖKERTMEMELİ → KOD_HATALARI DAHİL tüm hataları yut (index'ten farklı: index
            # re-raise eder, bellek etmez — bilinçli asimetri). GÖZLEMLENEBİLİRLİK (review tur-3):
            # bellek_eklendi bayrağı = sessiz-sonsuz-gizleme değil; kalıcı bellek-bug'ı
            # bellek_eklendi=False ile yüzeye çıkar (dev "bellek hiç eklenmiyor" sinyalini görür).
            try:
                memory_al().ekle(
                    govde_index[:1000],
                    {"video_id": kayit.video_id, "kaynak_turu": kayit.kaynak_turu},
                )
                bellek_eklendi = True
            except Exception:  # noqa: BLE001 — bellek best-effort: analiz bellek-hatasında kaybolmaz
                bellek_eklendi = False
        kaynak_sinyalleri = [
            KaynakSinyali.model_validate(sinyal)
            for sinyal in (state.get("kaynak_sinyalleri") or [])
        ]
        abstract_only = (
            kayit.kaynak_turu == "arxiv" and kayit.kaynak_ozel.get("text_scope") == "abstract_only"
        )
        summary_provenance = resmi.provenance() if resmi else {"method": "local_model_summary"}
        if abstract_only:
            summary_provenance = {
                "method": "source_sentence_selection_and_model_summary",
                "scope": "abstract_only",
                "layers": {
                    "kisa": "translated_source_sentences",
                    "orta": "translated_source_sentences",
                    "detay": "local_model_summary",
                },
                "reference": "icerik_tr",
                "reference_sha256": hashlib.sha256(
                    (state.get("icerik_tr") or "").encode("utf-8")
                ).hexdigest(),
                "original_reference": "01_kaynak-icerigi.md",
                "original_text_sha256": kayit.kaynak_ozel.get("original_text_sha256"),
                "source_language": kayit.anadil,
                "translation_status": ceviri_durumu,
                "independent_verification": False,
            }
        sonuc = AnalizSonucu(
            index=kayit,
            klasor=str(klasor),
            pii_tespit=bool(state.get("pii_tespit")),
            cloud_cagrisi_sayisi=int(state.get("cloud_cagrisi_sayisi", 0)),
            hedef=state.get("hedef", "local"),
            karmasiklik=state.get("karmasiklik", ""),
            cloud_girdi_token=int(state.get("cloud_girdi_token", 0)),
            cloud_cikti_token=int(state.get("cloud_cikti_token", 0)),
            kaynak_turu=state.get("kaynak_turu", kayit.kaynak_turu),
            kaynak_durumu=state.get("kaynak_durumu", durum),
            kaynak_sinyalleri=kaynak_sinyalleri,
            ollama_ping_ms=state.get("ollama_ping_ms"),
            transkript_durumu=durum,
            transkript_kaynak_dil=state.get("transkript_kaynak_dil"),
            transkript_karakter=len(metin.strip()),
            asr_tier=state.get("asr_tier"),
            ceviri_durumu=ceviri_durumu,
            dokum_segment_sayisi=int(state.get("dokum_segment_sayisi", 0)),
            ozet_faithfulness=state.get("ozet_faithfulness"),
            ozet_faithfulness_durum=state.get("ozet_faithfulness_durum"),
            analysis_mode=MODE if resmi else "model_analysis",
            quality_provenance={
                "summary": summary_provenance,
                "faithfulness": {
                    "method": "not_evaluated_direct_quotes" if resmi else "local_model_claim_judge",
                    "evaluated_output": "ozet_detay",
                    "reference": "icerik_tr",
                    "reference_sha256": hashlib.sha256(
                        (state.get("icerik_tr") or "").encode("utf-8")
                    ).hexdigest(),
                    "independent_verification": False,
                    "scope": "source_quotes_not_independent_verification"
                    if resmi
                    else "support_estimate_not_factual_accuracy",
                },
                "source": {
                    "acquisition_status": state.get("kaynak_durumu", durum),
                    "bytes_sha256": kayit.kaynak_ozel.get("source_bytes_sha256"),
                    "encoding": kayit.kaynak_ozel.get("encoding"),
                    "language_source": kayit.kaynak_ozel.get("language_source"),
                    "translation_status": ceviri_durumu,
                    "text_scope": kayit.kaynak_ozel.get("text_scope"),
                    "full_text_fetched": kayit.kaynak_ozel.get("full_text_fetched"),
                    "original_text_sha256": kayit.kaynak_ozel.get("original_text_sha256"),
                },
                "factcheck": {
                    "confidence_scope": "not_evaluated_normative_source"
                    if resmi
                    else "search_snippets_not_independent_verification"
                    if any(i.get("kanit_turu") == "arama_ozeti" for i in factcheck_iddialar)
                    else "uncalibrated_model_heuristic",
                    "reason": state.get("factcheck_reason", ""),
                    "primary_source_url": resmi.url if resmi else None,
                    "independent_verification": False,
                },
                "valuation": {"scope": "information_value_not_accuracy"},
                "personal_analysis": {
                    "scope": "not_generated_normative_source"
                    if resmi
                    else "model_interpretation_not_source_fact"
                },
            },
            # Faz 9: içerik METNİ sonuca (GUI inline gösterim) — dosyaya yazılanla aynı kaynak.
            ozet_kisa=ozet.get("kisa", ""),
            ozet_orta=ozet.get("orta", ""),
            ozet_detay=ozet.get("detay", ""),
            degerleme_puani=degerleme_puani,
            degerleme_durum=state.get("degerleme_durum", "atlandi"),
            kisisel_durum=state.get("kisisel_durum", "atlandi"),
            kisisel_analiz=kisisel_metni,
            factcheck_durum=factcheck_durum,
            factcheck_reason=state.get("factcheck_reason", ""),
            factcheck_iddia_sayisi=len(factcheck_iddialar),
            # dict → FactIddia (state ham dict tutar; sonuç modeli tipli — GUI kart render).
            factcheck_iddialar=[FactIddia.model_validate(it) for it in factcheck_iddialar],
            sunum_durum=sunum_durum,
            index_eklendi=index_eklendi,
            bellek_eklendi=bellek_eklendi,
            # Hata detayları + motor kökeni (GUI 'Hata'nın yanında nedeni gösterir).
            transkript_hata=state.get("transkript_hata", "") or "",
            degerleme_hata=state.get("degerleme_hata", "") or "",
            kisisel_hata=state.get("kisisel_hata", "") or "",
            factcheck_hata=state.get("factcheck_hata", "") or "",
            harita_hata=state.get("harita_hata", "") or "",
            ses_hata=state.get("ses_hata", "") or "",
            motor=motor,
            stub=False,
        )
    return {"klasor": str(klasor), "sonuc": sonuc.model_dump()}


def graph_olustur(checkpointer: Any) -> Any:
    # Faz 2 içerik node'ları (LOCAL/Ollama, torch-free) router'dan SONRA → Faz 1'in
    # pii_gate→router→0-cloud kanıtı birebir korunur (içerik hattı cloud kararını değiştirmez).
    from ytcore.content.node import ceviri_node, dokum_node, ozet_node, temizle_node

    # Faz 3 zeka node'ları (değerleme/kişisel = sıfır-egress local; fact-check = web-gated
    # anonim+anahtarsız-inert). ozet'ten SONRA → Faz 1/2 kanıtı bozulmaz.
    from ytcore.intel.node import degerleme_node, factcheck_node, kisisel_node

    # Faz 4 üretim node'ları (harita = local-render 0-egress; seslendirme = KVKK-gated TTS).
    # output'tan SONRA → klasör + sonuc hazır; Faz 1/2/3 0-cloud kanıtı BİREBİR korunur.
    from ytcore.uretim.node import harita_node, seslendirme_node

    g = StateGraph(GState)
    g.add_node("transcript", _transcript_node)
    g.add_node("temizle", temizle_node)
    g.add_node("pii_gate", _pii_gate_node)
    g.add_node("router", _router_node)
    g.add_node("local_ping", _local_ping_node)
    g.add_node("ceviri", ceviri_node)
    g.add_node("dokum", dokum_node)
    g.add_node("ozet", ozet_node)
    g.add_node("degerleme", degerleme_node)
    g.add_node("kisisel", kisisel_node)
    g.add_node("factcheck", factcheck_node)
    g.add_node("output", _output_node)
    g.add_node("harita", harita_node)
    g.add_node("seslendirme", seslendirme_node)
    g.add_edge(START, "transcript")
    # Faz 6 (#1): temizle transcript'ten SONRA, pii_gate'ten ÖNCE → gate TEMİZ metni denetler,
    # 01_transcript_orijinal.md temiz yazılır (0-cloud kanıtı korunur: temizle LOCAL Ollama).
    g.add_edge("transcript", "temizle")
    g.add_edge("temizle", "pii_gate")
    g.add_edge("pii_gate", "router")
    g.add_edge("router", "local_ping")
    g.add_edge("local_ping", "ceviri")
    g.add_edge("ceviri", "dokum")
    g.add_edge("dokum", "ozet")
    g.add_edge("ozet", "degerleme")
    g.add_edge("degerleme", "kisisel")
    g.add_edge("kisisel", "factcheck")
    g.add_edge("factcheck", "output")
    g.add_edge("output", "harita")
    g.add_edge("harita", "seslendirme")
    g.add_edge("seslendirme", END)
    return g.compile(checkpointer=checkpointer)

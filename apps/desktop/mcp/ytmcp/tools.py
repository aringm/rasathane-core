"""Faz 5 MCP adım-tool çekirdekleri — Mod A (abonelik): host LLM bu tool'ları zincirler.

Tüm fonksiyonlar senkron + stateless (girdi → JSON çıktı). A12 doğrulama: MCP Tasks
(task=True) Claude Code'da çalışmaz, sampling desteklenmez → sunucu pasif veri sağlar.
KVKK: çıktılarda video/ham-ses YOK (uzak MCP yalnız JSON taşır — Cloudflare ToS + m.9).
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any

from ytcore.config import get_config


def transcript_al_core(url: str, asr_izin: bool = False) -> dict[str, Any]:
    from ytcore.transcript.asr import SubprocessASR
    from ytcore.transcript.fetcher import fetcher_al
    from ytcore.transcript.node import transkript_uret

    cfg = get_config()
    t = transkript_uret(fetcher_al(), url, asr_izin, SubprocessASR(python=cfg.asr_python))
    return {
        "durum": t.durum,
        "metin": t.metin,
        "kaynak_dil": t.kaynak_dil,
        "asr_tier": t.asr_tier,
    }


def cevir_core(metin: str) -> dict[str, Any]:
    from ytcore.content.ceviri import cevir
    from ytcore.content.glossary import glossary_few_shot, varsayilan_glossary
    from ytcore.content.llm import llm_al

    cfg = get_config()
    tr = cevir(
        metin,
        llm_al(cfg.ollama_ceviri_model),
        glossary_metni=glossary_few_shot(varsayilan_glossary()),
        model=cfg.ollama_ceviri_model,
    )
    return {"durum": "cevrildi" if tr.strip() else "icerik_yok", "icerik_tr": tr}


def ozetle_core(metin: str) -> dict[str, Any]:
    from ytcore.content.llm import llm_al
    from ytcore.content.ozet import ozetle
    from ytcore.infra.embedding import embedding_al

    cfg = get_config()
    o = ozetle(
        metin,
        llm_al(cfg.ollama_map_model),
        embedding_al(),
        map_model=cfg.ollama_map_model,
        reduce_model=cfg.ollama_reduce_model,
    )
    kisa, detay = o.get("kisa", ""), o.get("detay", "")
    # boş≠başarı (review tur-1): pipeline ile aynı disiplin — boş özet 'başarı' değil.
    durum = "uretildi" if (kisa.strip() or detay.strip()) else "icerik_yok"
    return {"durum": durum, "kisa": kisa, "detay": detay}


def dokum_cikar_core(metin: str) -> dict[str, Any]:
    from ytcore.content.dokum import dokum_derle
    from ytcore.content.llm import llm_al
    from ytcore.infra.embedding import embedding_al

    cfg = get_config()
    bolumler = dokum_derle(
        metin, embedding_al(), llm=llm_al(cfg.ollama_map_model), model=cfg.ollama_map_model
    )
    # boş≠başarı: dokum_derle docstring'i "boş döküm 'başarı' verme — guard'la" der.
    return {
        "durum": "uretildi" if bolumler else "icerik_yok",
        "bolumler": [dataclasses.asdict(b) for b in bolumler],
    }


def degerlendir_core(metin: str, konu: str = "genel", baslik: str = "") -> dict[str, Any]:
    from datetime import date

    from ytcore.infra.embedding import embedding_al
    from ytcore.infra.index import index_al
    from ytcore.intel.degerleme import bilgi_degeri
    from ytcore.models import IndexKaydi

    # boş≠başarı (review tur-1 HIGH): boş gövde soğuk-başlangıç faktörlerinden 65.0 "puan"
    # almasın — pipeline degerleme_node ile aynı guard (sahte skor = yanıltıcı).
    if not metin.strip():
        return {"durum": "icerik_yok", "puan": None, "faktorler": {}}
    from ytcore.content.keyword import keyword_cikar

    embed = embedding_al()
    # keywords'ü içerikten türet (denetim MED): boş keywords → rarity DAİMA nötr 50.0 olurdu
    # (degerleme.py `not kayit.keywords` dalı), puanın %25'i sabitlenirdi. Pipeline
    # degerleme_node dökümden keyword enjekte ediyor; MCP yolu da aynı kaynağı kullanmalı.
    kws = keyword_cikar(metin, ust_n=15, embed=embed)
    kayit = IndexKaydi(
        video_url="",
        video_id="mcp-degerlendir",
        baslik=baslik or "(MCP girdisi)",
        anadil="tr",
        kanal="",
        konu=konu,
        uretici_slug="mcp",
        video_slug="mcp",
        analiz_tarihi=date.today().isoformat(),
        keywords=kws,
    )
    puan, fakt = bilgi_degeri(kayit, metin, embed, index_al())
    return {"durum": "uretildi", "puan": puan, "faktorler": fakt.model_dump()}


def fact_check_core(metin: str) -> dict[str, Any]:
    from ytcore.content.llm import llm_al
    from ytcore.intel.factcheck import fact_check
    from ytcore.intel.websearch import websearch_al
    from ytcore.router.ner import ner_al

    cfg = get_config()
    # NER yalnız web-egress mümkünken (intel/node.py factcheck_node ile AYNI karar;
    # tavily sayılmaz — client'ı yok, review tur-1).
    web_mumkun = bool(
        cfg.serper_api_key
        or cfg.searxng_url
        or cfg.firecrawl_url
        or os.environ.get("YT_WEBSEARCH_FIXTURE")
    )
    iddialar, durum = fact_check(
        metin,
        llm_al(cfg.ollama_verdict_model),
        websearch_al(),
        model=cfg.ollama_verdict_model,
        ner=ner_al() if web_mumkun else None,
        web_mumkun=web_mumkun,
    )
    return {"durum": durum, "iddialar": iddialar}


def _agac_to_dict(d: Any) -> dict[str, Any]:
    return {
        "label": d.label,
        "zaman_sn": d.zaman_sn,
        "cocuklar": [_agac_to_dict(c) for c in d.cocuklar],
    }


def zihin_haritasi_core(
    metin: str, konu: str = "genel", html_dosya: str | None = None
) -> dict[str, Any]:
    from ytcore.content.llm import llm_al
    from ytcore.uretim.harita import agac_to_markmap, dugum_say, harita_agaci
    from ytcore.uretim.markmap import markmap_html

    cfg = get_config()
    agac = harita_agaci(metin, llm_al(cfg.harita_model), model=cfg.harita_model)
    n = dugum_say(agac)
    # boş≠başarı (review tur-1): pipeline harita_node ile aynı eşik — dejenere tek-düğüm
    # ağaç 'üretildi' değildir; o durumda HTML de YAZILMAZ.
    if n <= 1:
        return {"durum": "icerik_yok", "dugum_sayisi": n, "agac": _agac_to_dict(agac)}
    sonuc: dict[str, Any] = {
        "durum": "uretildi",
        "dugum_sayisi": n,
        "agac": _agac_to_dict(agac),
    }
    if html_dosya:  # HTML string DÖNDÜRÜLMEZ (vendored JS ~400KB) — dosyaya yaz, yolu döndür
        veri = agac_to_markmap(agac)
        p = Path(html_dosya)
        # Üst dizini oluştur (denetim LOW): yoksa LLM maliyeti harcandıktan SONRA ham
        # FileNotFoundError fırlardı + hesaplanan ağaç kaybolurdu. TTS sağlayıcı deseniyle hizalı.
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(markmap_html(veri, baslik=konu), encoding="utf-8")
            sonuc["html_dosya"] = html_dosya
        except OSError as e:  # ağaç korunur (kısmi başarı); LLM işi boşa gitmesin
            sonuc["html_hata"] = f"{type(e).__name__}: {str(e)[:200]}"
    return sonuc


def seslendir_core(metin: str, hedef_dosya: str | None = None) -> dict[str, Any]:
    from ytcore.uretim.tts import seslendirme_karari, tts_al, tts_pii_var_mi

    cfg = get_config()
    # KVKK gate — tts_pii_var_mi: pipeline seslendirme_node ile TEK ortak enforcement
    # (review tur-1: kopya gate sapması yok).
    pii = tts_pii_var_mi(metin)
    kaynak, gerekce = seslendirme_karari(
        pii_var=pii, cloud_acik=cfg.tts_cloud_acik, anahtar_var=bool(cfg.openai_api_key)
    )
    # Uzantı SAĞLAYICI kararına göre (denetim LOW): cloud=MP3, piper/fake=WAV. hedef_dosya
    # verilse bile uzantıyı düzelt — .wav yola MP3 bayt (veya tersi) yazılıp yanıltmasın.
    ext = ".mp3" if kaynak == "cloud" else ".wav"
    hedef = (
        Path(hedef_dosya).with_suffix(ext)
        if hedef_dosya
        else cfg.output_base / "_mcp" / f"seslendirme{ext}"
    )
    s = tts_al(kaynak).seslendir(metin, hedef)
    return {
        "durum": s.durum,
        "kaynak": s.kaynak,
        "gerekce": gerekce,
        # boş≠başarı (review tur-1): dosya yolu yalnız GERÇEKTEN üretildiyse döner.
        "dosya": str(hedef) if s.durum == "uretildi" else None,
    }


def ollama_test_core(host: str | None = None) -> dict[str, Any]:
    """GUI Ayarlar 'Test Et' / 'kurulu Ollama + modelleri tespit': verilen (yoksa mevcut) host'u
    test eder → sürüm + yüklü model listesi. KVKK fail-closed: loopback OLMAYAN host bilinçli
    opt-in (YT_ALLOW_REMOTE_OLLAMA=1) olmadan İSTEK ATMADAN reddedilir."""
    import httpx
    from ytcore.config import _loopback_host_mi, _normalize_host

    ham = (host or "").strip() or get_config().ollama_host
    h = _normalize_host(ham)
    if not _loopback_host_mi(h) and os.environ.get("YT_ALLOW_REMOTE_OLLAMA") != "1":
        return {
            "erisilebilir": False,
            "host": h,
            "modeller": [],
            "hata": "KVKK: loopback olmayan host — YT_ALLOW_REMOTE_OLLAMA=1 olmadan test edilmez "
            "(PII içerik uzak servise gidebilir).",
        }
    surum: str | None = None
    try:
        rv = httpx.get(f"{h}/api/version", timeout=3.0)
        rv.raise_for_status()
        surum = str(rv.json().get("version", "")) or None
    except Exception:  # noqa: BLE001 — sürüm yoksa yine modelleri dene (graceful)
        surum = None
    modeller: list[str] = []
    try:
        rt = httpx.get(f"{h}/api/tags", timeout=3.0)
        rt.raise_for_status()
        modeller = [str(m.get("name", "")) for m in rt.json().get("models", []) if m.get("name")]
    except Exception:  # noqa: BLE001 — ağ/HTTP ham hata sınırda graceful
        modeller = []
    erisilebilir = surum is not None or bool(modeller)
    sonuc: dict[str, Any] = {
        "erisilebilir": erisilebilir,
        "host": h,
        "surum": surum,
        "model_sayisi": len(modeller),
        "modeller": modeller,
    }
    if not erisilebilir:
        sonuc["hata"] = (
            "Ollama'ya ulaşılamadı. Kurulu ve çalışıyor mu? (Ollama'yı başlatın; "
            "model için: 'ollama pull qwen2.5:14b' ve 'ollama pull bge-m3')"
        )
    return sonuc


def ayarlar_oku_core() -> dict[str, Any]:
    """GUI Ayarlar: etkin değerler + kalıcı ayarlar + host kaynağı (env/ayar/varsayılan)."""
    from ytcore.config import _ayarlar_oku, motor_kok_bul

    cfg = get_config()
    kayitli = _ayarlar_oku(cfg.output_base)
    kaynak = (
        "env"
        if os.environ.get("OLLAMA_HOST")
        else "ayar"
        if isinstance(kayitli.get("ollama_host"), str)
        else "varsayilan"
    )
    mk = motor_kok_bul()
    return {
        "ollama_host": cfg.ollama_host,
        "ollama_host_kaynak": kaynak,
        "motor_kok": str(mk) if mk else None,
        "output_base": str(cfg.output_base),
        "kayitli_ayarlar": kayitli,
    }


def _motor_kok_gecerli(p: Path) -> bool:
    """Motor kökü .venv/python + core/ytcore içeriyor mu (NER/TTS worker'ları için)."""
    rel = Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python")
    try:
        return (p / ".venv" / rel).is_file() and (p / "core" / "ytcore").is_dir()
    except OSError:
        return False


def ayarlar_kaydet_core(
    ollama_host: str | None = None, motor_kok: str | None = None
) -> dict[str, Any]:
    """GUI Ayarlar 'Kaydet': _ayarlar.json'a yazar. KVKK: loopback olmayan host opt-in olmadan
    REDDEDİLİR. motor_kok geçersizse (.venv+core yok) reddedilir. Boş değer → ayar silinir
    (varsayılana/oto-tespite döner). OLLAMA_HOST env set ise env önceliklidir (env_override)."""
    import json

    from ytcore.config import _ayarlar_oku, _loopback_host_mi, _normalize_host, ayarlar_yolu

    cfg = get_config()
    mevcut = _ayarlar_oku(cfg.output_base)
    if ollama_host is not None:
        ham = ollama_host.strip()
        if ham:
            h = _normalize_host(ham)
            if not _loopback_host_mi(h) and os.environ.get("YT_ALLOW_REMOTE_OLLAMA") != "1":
                return {
                    "durum": "reddedildi",
                    "hata": "KVKK: loopback olmayan host kaydedilemez (YT_ALLOW_REMOTE_OLLAMA=1 "
                    "olmadan). PII içerik uzak servise gidebilir.",
                }
            mevcut["ollama_host"] = h
        else:
            mevcut.pop("ollama_host", None)  # boş → varsayılana dön
    if motor_kok is not None:
        ham = motor_kok.strip()
        if ham:
            if not _motor_kok_gecerli(Path(ham)):
                return {
                    "durum": "reddedildi",
                    "hata": "Geçersiz motor kökü: `.venv` (python) ve `core/ytcore` içermeli "
                    "(NER + sesli özet için). Doğru klasör: youtube-analiz-sistemi.",
                }
            mevcut["motor_kok"] = str(Path(ham).resolve())
        else:
            mevcut.pop("motor_kok", None)  # boş → oto-tespite dön
    p = ayarlar_yolu(cfg.output_base)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mevcut, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "durum": "kaydedildi",
        "kayitli_ayarlar": mevcut,
        "env_override": bool(os.environ.get("OLLAMA_HOST")),
    }


def ses_modeli_indir_core() -> dict[str, Any]:
    """Piper TR voice modelini (tr_TR-dfki-medium) HuggingFace'den indir — GUI/operatör
    bilinçli tetikler (analiz ortasında sürpriz indirme YOK; tts.py:182 deseni). KVKK:
    yalnız MODEL indirir (local'e veri çeker) — kullanıcı/video verisi egress YOK.

    Durumlar: zaten_var | indirildi | hata. Boş≠başarı: indirme sonrası piper_hazir_mi ile
    (.onnx + .onnx.json İKİSİ) doğrulanır; yarım indirme 'indirildi' raporlanmaz."""
    from ytcore.uretim.tts import piper_hazir_mi, piper_voice_indir

    cfg = get_config()
    if piper_hazir_mi(cfg.piper_voice_dir):
        return {"durum": "zaten_var", "yol": str(cfg.piper_voice_dir)}
    try:
        piper_voice_indir(cfg.piper_voice_dir)
    except Exception as e:  # noqa: BLE001 — ağ/HTTP/IO ham hata sınırda graceful (CORS'lu döner)
        return {"durum": "hata", "hata": f"{type(e).__name__}: {str(e)[:200]}"}
    if not piper_hazir_mi(cfg.piper_voice_dir):
        return {"durum": "hata", "hata": "indirme tamamlanamadi (eksik dosya)"}
    return {"durum": "indirildi", "yol": str(cfg.piper_voice_dir)}


def indeks_ara_core(sorgu: str, k: int = 5) -> dict[str, Any]:
    from ytcore.infra.index import index_al

    # k doğrulama + durum alanı (denetim LOW): diğer 11 tool'da var; boş korpus ile
    # eşleşme-yok ayırt edilebilsin. k makul aralığa sıkıştırılır (negatif/aşırı değer guard).
    k = max(1, min(int(k or 5), 50))
    if not sorgu.strip():
        return {"durum": "icerik_yok", "sonuclar": []}
    kayitlar = index_al().ara(sorgu, k)
    return {
        "durum": "uretildi" if kayitlar else "sonuc_yok",
        "sonuclar": [
            {
                "baslik": r.baslik,
                "video_url": r.video_url,
                "kaynak_turu": r.kaynak_turu,
                "kaynak_url": r.kaynak_url or r.video_url,
                "kaynak_id": r.kaynak_id or r.video_id,
                "kaynak_sahibi": r.kaynak_sahibi or r.kanal,
                "konu": r.konu,
                "analiz_tarihi": r.analiz_tarihi,
                "degerleme_puani": r.degerleme_puani,
            }
            for r in kayitlar
        ],
    }


def modeller_core() -> dict[str, Any]:
    """Aktif backend'in modellerini generation/embedding ayrımıyla listele.

    GUI 'Üretim modeli' seçici bunu tüketir. Backend llamacpp ise gömülü motorun profil
    modelleri döner (Ollama listesi YANILTICI olurdu — 2026-08-24 saha dersi: kullanıcı
    hangi modelle çalıştığını göremiyordu). Ollama backend'inde embedding (bge-m3,
    family=bert) generation listesinden ELENİR (sabit; RAG/index'i kırmamak için).
    Ollama kapalı -> modeller:[]."""
    from ytcore.infra.vram import VRAM_BUTCE, vram_tahmin_gb
    from ytcore.local.ollama_ping import modeller_listele

    cfg = get_config()
    if cfg.motor_backend == "llamacpp":
        # Gömülü motor: tek LLM + tek embedding profili. Dosya boyutları kökten okunur
        # (VRAM tahmini anlamsız — CPU/RAM profili; boyut bilgisi yeterli köken kanıtı).
        from ytcore.config import llamacpp_motor_kok
        from ytcore.local.llamacpp import aktif_profil, profil_bilgisi

        profil = aktif_profil()
        bilgi = profil_bilgisi(profil)
        kok = llamacpp_motor_kok()

        def _boyut(dosya: str) -> int:
            if kok is None:
                return 0
            try:
                return int((kok / "modeller" / dosya).stat().st_size)
            except OSError:
                return 0

        llm_dosya = str(bilgi["llm_dosya"])
        embed_dosya = str(bilgi["embed_dosya"])
        return {
            "backend": "llamacpp",
            "profil": profil,
            "modeller": [
                {
                    "ad": llm_dosya,
                    "parametre": "Gemma 4 QAT (gömülü)",
                    "quant": "Q4_K_XL",
                    "boyut_bayt": _boyut(llm_dosya),
                    "vram_tahmin_gb": None,
                    "vram_durum": "yerel-cpu",
                }
            ],
            "embedding_modeller": [{"ad": embed_dosya, "parametre": "bge-m3 (gömülü)"}],
            "ollama_erisilebilir": bool(modeller_listele(cfg.ollama_host)),
            "varsayilan": llm_dosya,
            "num_ctx": int(bilgi["num_ctx"]),
            "limit_gb": VRAM_BUTCE["limit_gb"],
        }
    ham = modeller_listele(cfg.ollama_host)
    generation: list[dict[str, Any]] = []
    embedding: list[dict[str, Any]] = []
    for m in ham:
        if m.get("embedding_mi"):
            embedding.append({"ad": m["ad"], "parametre": m.get("parametre", "")})
            continue
        gb, durum = vram_tahmin_gb(str(m.get("parametre", "")), cfg.ollama_num_ctx)
        generation.append(
            {
                "ad": m["ad"],
                "parametre": m.get("parametre", ""),
                "quant": m.get("quant", ""),
                "boyut_bayt": m.get("boyut_bayt", 0),
                "vram_tahmin_gb": gb,
                "vram_durum": durum,
            }
        )
    return {
        "backend": "ollama",
        "modeller": generation,
        "embedding_modeller": embedding,
        "ollama_erisilebilir": bool(ham),
        "varsayilan": cfg.ollama_reduce_model,
        "num_ctx": cfg.ollama_num_ctx,
        "limit_gb": VRAM_BUTCE["limit_gb"],
    }


def kutuphane_listele_core() -> list[dict[str, Any]]:
    """Geçmiş analizleri listele: output_base altındaki 00_index.json dosyalarını TARA
    (index.ara DEĞİL — o arama-bazlı + kanal/konu/tarih alanlarını boş döndürür). Bozuk/yarım
    JSON fail-soft atlanır (tek klasör tüm listeyi çökertmesin). analiz_tarihi azalan sıralı.
    Boş/yok base -> [] (ilk kullanım). 'klasor' = /gui/klasor_ac'in beklediği mutlak yol."""
    import json

    base = get_config().output_base
    if not base.exists():
        return []
    kayitlar: list[dict[str, Any]] = []
    for p in base.rglob("00_index.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # fail-soft
        if not isinstance(d, dict):
            continue
        kayitlar.append(
            {
                "baslik": d.get("baslik") or "(başlık yok)",
                "kanal": d.get("kanal") or "",
                "tarih": d.get("analiz_tarihi") or "",
                "yayin_tarihi": d.get("yayin_tarihi") or "",
                "konu": d.get("konu") or "genel",  # JSON ham değer (klasör slug'ı DEĞİL)
                "puan": d.get("degerleme_puani"),
                "klasor": str(p.parent),
                "video_id": d.get("video_id") or "",
                "kaynak_turu": d.get("kaynak_turu") or "youtube",
                "kaynak_url": d.get("kaynak_url") or d.get("video_url") or "",
                "kaynak_id": d.get("kaynak_id") or d.get("video_id") or "",
                "kaynak_sahibi": d.get("kaynak_sahibi") or d.get("kanal") or "",
            }
        )
    kayitlar.sort(key=lambda k: str(k["tarih"]), reverse=True)
    return kayitlar


def _searxng_erisilebilir_mi() -> bool:
    """Best-effort: YAPILANDIRILMIŞ SearXNG (YT_SEARXNG_URL) aktif mi. Opt-in DEĞİLse False —
    rozet websearch_al sağlayıcı seçimiyle hizalı (default-port probe'u yanıltıcı 'aktif' demesin;
    review MED: aksi hâlde rozet 'aktif' der ama fact-check Serper'a düşüp 'web_yok' üretir)."""
    if not get_config().searxng_url:
        return False
    from ytcore.intel.websearch import SearXNGSearch

    try:
        return SearXNGSearch().ara_durumlu("test", 1)[1] == "aktif"
    except Exception:  # noqa: BLE001 — durum sorgusu kritik yol değil
        return False


def _firecrawl_erisilebilir_mi() -> bool:
    """Best-effort HAFİF reachability (GET / — gerçek arama DEĞİL; GUI her açılışta çağırır,
    30s'lik /v1/search yapılmaz). Yalnız loopback (KVKK). firecrawl_url kapalıysa False."""
    cfg = get_config()
    if not cfg.firecrawl_url:
        return False
    from ytcore.config import _loopback_host_mi, _normalize_host

    taban = _normalize_host(cfg.firecrawl_url)
    if not _loopback_host_mi(taban):
        return False
    import httpx

    try:
        return httpx.get(f"{taban}/", timeout=3.0).status_code == 200
    except Exception:  # noqa: BLE001 — durum sorgusu kritik yol değil
        return False


def _ner_erisilebilir_mi() -> bool:
    """Best-effort: yapılandırılmış ner_python transformers'ı IMPORT edebiliyor mu (HAFİF —
    modeli YÜKLEMEZ; 60s model-load yerine ~1s find_spec probe). YT_NER_FIXTURE → True (FakeNER
    selftest/hermetik; spawn YOK). Frozen exe kendini gösteriyorsa (transformers PYZ'de yok)
    spawn ETMEDEN False. KVKK: NER yoksa web fact-check fail-closed — rozet bunu yüzeyler."""
    if os.environ.get("RASATHANE_WORKER_EXE", "").strip():
        from rasathane.product.capabilities import packaged_runtime_status

        return bool(packaged_runtime_status()["ner_erisilebilir"])
    if os.environ.get("YT_NER_FIXTURE", "").strip():
        return True
    import sys

    from ytcore.router.ner import _ayni_yol

    py = get_config().ner_python
    # frozen-self: NORMALİZE yol karşılaştırması (ner.py emsali; raw == case/symlink/../ varyantını
    # kaçırırdı → gereksiz self-spawn). py exe'nin kendisiyse probe ETME (transformers PYZ'de yok).
    if getattr(sys, "frozen", False) and _ayni_yol(py, sys.executable):
        return False
    import subprocess

    # GÜVENLİK (review): probe'a secret env (API anahtarı/token/parola) + PYTHONPATH MİRAS VERME
    # (poisoned-python + sandbox hijyeni; find_spec yalnız PATH/SystemRoot ister). Son-ek deseni →
    # gelecekte eklenen secret'lar da otomatik dışlanır (deny-by-default; deny-list bakım yükü yok).
    _gizli_son = ("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
    cocuk_env = {
        k: v for k, v in os.environ.items() if k != "PYTHONPATH" and not k.endswith(_gizli_son)
    }
    try:
        proc = subprocess.run(
            [
                py,
                "-c",
                "import importlib.util,sys;"
                "sys.exit(0 if importlib.util.find_spec('transformers') else 1)",
            ],
            capture_output=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            env=cocuk_env,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ner_kaynak() -> str:
    """NER python'unun KAYNAĞI (GUI/runbook teşhisi): fixture/env/venv-oto/yok/dev."""
    import sys

    from ytcore.router.ner import _ayni_yol

    if os.environ.get("RASATHANE_WORKER_EXE", "").strip():
        from rasathane.product.capabilities import packaged_runtime_status

        return str(packaged_runtime_status()["ner_kaynak"])
    if os.environ.get("YT_NER_FIXTURE", "").strip():
        return "fixture"
    if os.environ.get("YT_NER_PYTHON", "").strip():
        return "env"
    if getattr(sys, "frozen", False):
        # NORMALİZE karşılaştırma (ner.py emsali) — raw == yanlış 'venv-oto'/'yok' etiketi verirdi.
        return "yok" if _ayni_yol(get_config().ner_python, sys.executable) else "venv-oto"
    return "dev"


def kurulum_kontrol_core() -> dict[str, Any]:
    from ytcore.config import motor_kok_bul
    from ytcore.local.ollama_ping import ollama_erisilebilir
    from ytcore.uretim.tts import piper_hazir_mi

    cfg = get_config()
    _ollama = ollama_erisilebilir()
    _ner = _ner_erisilebilir_mi()
    _piper = piper_hazir_mi(cfg.piper_voice_dir)
    _mk = motor_kok_bul()
    result = {
        "ollama_erisilebilir": _ollama,
        # .onnx VE .onnx.json İKİSİ birden (denetim MED: yarım indirme 'hazır' raporlanmasın).
        "piper_voice_hazir": _piper,
        "anthropic_anahtar_var": bool(cfg.anthropic_api_key),
        "openai_anahtar_var": bool(cfg.openai_api_key),
        "github_token_var": bool(os.environ.get("GITHUB_TOKEN")),
        "hf_token_var": bool(os.environ.get("HF_TOKEN")),
        "reddit_token_var": bool(os.environ.get("REDDIT_ACCESS_TOKEN")),
        # Yalnız Serper (denetim MED): Tavily client'ı YOK (intel/node.py:95 ile tutarlı) —
        # TAVILY_API_KEY'i sayan eski sinyal yanıltıcıydı (web fact-check fiilen Serper'a bağlı).
        "websearch_anahtar_var": bool(cfg.serper_api_key),
        # Faz 7: SearXNG yerel web arama — kurulu/ayakta mı + aktif sağlayıcı (GUI rozeti).
        "searxng_url": cfg.searxng_url or "(ayarlı değil — YT_SEARXNG_URL)",
        "searxng_erisilebilir": _searxng_erisilebilir_mi(),
        "firecrawl_url": cfg.firecrawl_url or "(kapalı)",
        "firecrawl_erisilebilir": _firecrawl_erisilebilir_mi(),
        "websearch_saglayici": (
            "searxng"
            if cfg.searxng_url
            else "serper"
            if cfg.serper_api_key
            else "firecrawl"
            if cfg.firecrawl_url
            else "yok"
        ),
        "cloud_verdict_acik": cfg.cloud_verdict_acik,
        "tts_cloud_acik": cfg.tts_cloud_acik,
        # Piper TTS AYRI PROSES (ASR/NER deseni): worker'ı koşan python — frozen GUI'de sesli
        # özet sentezi bu env'in piper'lı olmasına bağlı (operatöre görünür).
        "tts_python": cfg.tts_python,
        "ner_python": cfg.ner_python,
        # Faz 8: GUI rozeti — gerçek NER motoru (transformers) erişilebilir mi + kaynağı.
        # NER yoksa web fact-check fail-closed (egress bloklanır); operatöre GÖRÜNÜR olmalı.
        "ner_erisilebilir": _ner,
        "ner_kaynak": _ner_kaynak(),
        # Faz 10: motor kökü (NER/TTS worker'larının .venv+core'u) — kurulu app bunu açık
        # konumdan bulursa tam özellik olur; onboarding bununla yapılandırmaya yönlendirir.
        "motor_kok": str(_mk) if _mk else None,
        # 'tam özellik hazır mı': Ollama + NER + Piper hepsi tamam → onboarding gerekmez.
        "tam_ozellik_hazir": bool(_ollama and _ner and _piper),
        # review tur-1 MED: YT_NER_FIXTURE tek fail-open seam (guard'ı zayıflatır) —
        # operatöre GÖRÜNÜR olmalı; üretimde set OLMAMALI (runbook güvenlik listesi).
        "ner_fixture_aktif": bool(os.environ.get("YT_NER_FIXTURE", "").strip()),
        # denetim (PewDiePie vakası): TÜM test fixture seam'leri görünür olmalı — set iseler
        # motor gerçek video yerine kanned içerik üretir. http/stdio başlangıcında _fixture_guard
        # bunları pop'lar; burası boş DÖNMELİ (boş değilse fixture sızıntısı = sahte sonuç riski).
        "fixture_aktif": sorted(
            k
            for k in os.environ
            if "FIXTURE" in k and (k.startswith("YT_") or k.startswith("RASATHANE_"))
        ),
        "output_base": str(cfg.output_base),
    }
    if os.environ.get("RASATHANE_WORKER_EXE", "").strip():
        from rasathane.product.capabilities import packaged_runtime_status
        from ytcore.local.llamacpp import _model_yolu, _sunucu_bin

        capabilities = packaged_runtime_status()
        result.update(capabilities)
        try:
            motor_ready = (
                all(_model_yolu(kind).is_file() for kind in ("llm", "embed"))
                and _sunucu_bin().is_file()
            )
        except (FileNotFoundError, OSError):
            motor_ready = False
        result["motor_hazir"] = motor_ready
        result["tam_ozellik_hazir"] = all(
            (
                motor_ready,
                capabilities["ner_erisilebilir"],
                capabilities["asr_hazir"],
                capabilities["tts_hazir"],
            )
        )
    return result

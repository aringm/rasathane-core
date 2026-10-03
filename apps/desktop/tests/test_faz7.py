"""Faz 7 testleri: local web search (SearXNG), model seçimi, kütüphane, dosya görüntüleme.

Hermetik: httpx monkeypatch (ağsız), tmp_output_base (diske yazmaz), ASGITransport (sidecar
spawn yok). KVKK/güvenlik invariantları (loopback guard, path-traversal, env-restore) doğrulanır.
"""

from __future__ import annotations

import json

import httpx


# --- VRAM tahmini (değişmez #2 kullanıcıya yüzeyler) --------------------------
def test_vram_tahmin_esikleri():
    from ytcore.infra.vram import vram_tahmin_gb

    gb14, d14 = vram_tahmin_gb("14.8B", 8192)
    assert gb14 is not None and 10.0 <= gb14 <= 12.0 and d14 == "guvenli"  # qwen2.5:14b ankoru
    _, d36 = vram_tahmin_gb("36.0B", 8192)
    assert d36 == "asar"  # qwen3.6:35b → 16GB aşar
    _, dsin = vram_tahmin_gb("20.0B", 8192)
    assert dsin == "sinir"  # 13-16 GB bandı
    gbm, dm = vram_tahmin_gb("566.70M", 8192)
    assert gbm is not None and dm == "guvenli"  # embedding boyutu
    assert vram_tahmin_gb("", 8192) == (None, "bilinmiyor")
    assert vram_tahmin_gb("abc", 8192) == (None, "bilinmiyor")
    # 8192 üstü ctx → ankor-dışı, en az 'sinir'e zorlanır (8B@8K güvenli, @32K sinir)
    assert vram_tahmin_gb("8.0B", 8192)[1] == "guvenli"
    assert vram_tahmin_gb("8.0B", 32768)[1] != "guvenli"


# --- SearXNG sağlayıcı (yerel web search) ------------------------------------
class _FakeResp:
    def __init__(self, status, veri):
        self.status_code = status
        self._veri = veri

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self):
        return self._veri


def test_searxng_aktif(monkeypatch):
    from ytcore.intel.websearch import SearXNGSearch

    veri = {"results": [{"title": "T1", "url": "https://x", "content": "ozet1"}]}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(200, veri))
    sonuc, durum = SearXNGSearch("http://127.0.0.1:8888").ara_durumlu("test", 3)
    assert durum == "aktif" and len(sonuc) == 1 and sonuc[0].baslik == "T1"


def test_searxng_403(monkeypatch):
    from ytcore.intel.websearch import SearXNGSearch

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp(403, {}))
    assert SearXNGSearch("http://127.0.0.1:8888").ara_durumlu("t")[1] == "searxng_403"


def test_searxng_baglanti_yok(monkeypatch):
    from ytcore.intel.websearch import SearXNGSearch

    def _patla(*a, **k):
        raise httpx.ConnectError("baglanti reddedildi")

    monkeypatch.setattr(httpx, "get", _patla)
    assert SearXNGSearch("http://127.0.0.1:8888").ara_durumlu("t")[1] == "baglanti_yok"


def test_searxng_uzak_engellendi():
    """KVKK: loopback olmayan SearXNG instance'ı reddedilir (deny-by-default, egress yapılmaz)."""
    from ytcore.intel.websearch import SearXNGSearch

    sonuc, durum = SearXNGSearch("http://uzak-sunucu.example.com:8888").ara_durumlu("t")
    assert durum == "uzak_engellendi" and sonuc == []


def test_websearch_al_oncelik(monkeypatch):
    """fixture → Fake; YT_SEARXNG_URL → SearXNG; firecrawl_url (default 3002) → Firecrawl;
    firecrawl kapalı + anahtarsız → Serper (web_yok)."""
    from ytcore.intel.websearch import (
        FakeWebSearch,
        FirecrawlSearch,
        SearXNGSearch,
        SerperSearch,
        websearch_al,
    )

    assert isinstance(websearch_al(), FakeWebSearch)  # conftest YT_WEBSEARCH_FIXTURE=1
    monkeypatch.delenv("YT_WEBSEARCH_FIXTURE", raising=False)
    monkeypatch.setenv("YT_SEARXNG_URL", "http://127.0.0.1:8888")
    assert isinstance(websearch_al(), SearXNGSearch)
    monkeypatch.delenv("YT_SEARXNG_URL", raising=False)
    monkeypatch.setenv("YT_FIRECRAWL_URL", "http://127.0.0.1:3002")  # firecrawl açık
    assert isinstance(websearch_al(), FirecrawlSearch)
    monkeypatch.setenv("YT_FIRECRAWL_URL", "")  # firecrawl kapalı → Serper fallback
    assert isinstance(websearch_al(), SerperSearch)


def test_firecrawl_aktif(monkeypatch):
    from ytcore.intel.websearch import FirecrawlSearch

    veri = {"success": True, "data": [{"url": "https://x", "title": "T1", "description": "ozet1"}]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResp(200, veri))
    sonuc, durum = FirecrawlSearch("http://127.0.0.1:3002").ara_durumlu("test", 2)
    assert durum == "aktif" and len(sonuc) == 1
    assert sonuc[0].baslik == "T1" and sonuc[0].ozet == "ozet1"


def test_firecrawl_baglanti_yok(monkeypatch):
    from ytcore.intel.websearch import FirecrawlSearch

    def _patla(*a, **k):
        raise httpx.ConnectError("kapali")

    monkeypatch.setattr(httpx, "post", _patla)
    assert FirecrawlSearch("http://127.0.0.1:3002").ara_durumlu("t")[1] == "baglanti_yok"


def test_firecrawl_uzak_engellendi():
    """KVKK: loopback olmayan Firecrawl reddedilir (egress yapılmaz)."""
    from ytcore.intel.websearch import FirecrawlSearch

    sonuc, durum = FirecrawlSearch("http://uzak-sunucu.example.com:3002").ara_durumlu("t")
    assert durum == "uzak_engellendi" and sonuc == []


def test_factcheck_baglanti_yok_web_hata():
    """SearXNG kapalı (baglanti_yok) → fact_check 'web_hata' döndürür (web_yok DEĞİL)."""
    from ytcore.content.llm import FakeLLM
    from ytcore.intel.factcheck import fact_check

    class _KapaliWeb:
        def ara_durumlu(self, sorgu, n=5):
            return [], "baglanti_yok"

    metin = "Türkiye'nin başkenti Ankara'dır. Bu doğru bir bilgidir."
    _, durum = fact_check(metin, FakeLLM(), _KapaliWeb())
    assert durum == "web_hata"


def test_factcheck_hepsi_atlandi():
    """TÜM iddialar NER (kişi) ile bloklanır + web mümkün → 'hepsi_atlandi' (web_yok DEĞİL).

    KVKK: kişi-yoğun içerikte her sorgu web'e gitmeden atlanır; servis vardı ama hepsi
    gate'lendi → kullanıcıya 'servis yok' değil 'kişisel veri nedeniyle atlandı' sinyali."""
    from ytcore.content.llm import FakeLLM
    from ytcore.intel.factcheck import fact_check

    class _HerKisiNer:
        def kisi_var_mi(self, sorgular):
            return [True] * len(sorgular)  # her sorgu kişi içeriyor → web'e GİTMEZ

    class _Web:
        def ara_durumlu(self, sorgu, n=5):
            return [], "aktif"  # çağrılmamalı (hepsi NER'de bloklanır)

    metin = "Birinci olgusal iddia burada yeterince uzun. İkinci iddia da uzun bir metin."
    _, durum = fact_check(metin, FakeLLM(), _Web(), ner=_HerKisiNer(), web_mumkun=True)
    assert durum == "hepsi_atlandi"


# --- modeller_core (model seçimi) --------------------------------------------
def test_modeller_core_embedding_eler(monkeypatch):
    from ytcore.local import ollama_ping
    from ytmcp import tools

    # Ollama dalını kilitler: dev makinesinde gömülü motor varsa auto→llamacpp sapması
    # bu testin amacını bozar (llamacpp dalı ayrıca test edilir).
    monkeypatch.setenv("YT_MOTOR_BACKEND", "ollama")

    def _m(ad, param, aile, emb):
        return {
            "ad": ad,
            "boyut_bayt": 1,
            "parametre": param,
            "quant": "Q4_K_M",
            "aile": aile,
            "embedding_mi": emb,
        }

    ham = [
        _m("qwen2.5:14b", "14.8B", "qwen2", False),
        _m("bge-m3:latest", "566.70M", "bert", True),
        _m("qwen3.6:35b", "36.0B", "qwen3", False),
    ]
    monkeypatch.setattr(ollama_ping, "modeller_listele", lambda host, timeout=3.0: ham)
    veri = tools.modeller_core()
    adlar = {m["ad"] for m in veri["modeller"]}
    assert adlar == {"qwen2.5:14b", "qwen3.6:35b"}  # bge-m3 (embedding) ELENDİ
    assert any(m["ad"] == "bge-m3:latest" for m in veri["embedding_modeller"])
    asar = next(m for m in veri["modeller"] if m["ad"] == "qwen3.6:35b")
    assert asar["vram_durum"] == "asar"  # 35B → 16GB aşar uyarısı


def test_modeller_core_llamacpp_profili(monkeypatch, tmp_path):
    """llamacpp backend'inde /gui/modeller gömülü motorun profilini döndürür — Ollama
    listesi YANILTICI olurdu (2026-08-24 saha dersi: kullanıcı hangi modelle çalıştığını
    göremiyordu). GGUF dosya adları + boyut + profil + backend alanı kilitlenir."""
    from ytcore.local import llamacpp, ollama_ping
    from ytmcp import tools

    modeller = tmp_path / "modeller"
    modeller.mkdir()
    for anahtar in ("llm_dosya", "embed_dosya"):
        (modeller / str(llamacpp.PROFILLER["ram8"][anahtar])).write_bytes(b"g" * 2048)
    monkeypatch.setenv("RASATHANE_MOTOR_DIR", str(tmp_path))
    monkeypatch.setenv("YT_MOTOR_BACKEND", "llamacpp")
    monkeypatch.setenv("YT_LLAMACPP_PROFIL", "ram8")
    monkeypatch.setattr(ollama_ping, "modeller_listele", lambda host, timeout=3.0: [])

    veri = tools.modeller_core()
    assert veri["backend"] == "llamacpp"
    assert veri["profil"] == "ram8"
    assert [m["ad"] for m in veri["modeller"]] == ["gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"]
    assert veri["modeller"][0]["boyut_bayt"] == 2048
    assert veri["embedding_modeller"][0]["ad"] == "bge-m3-Q4_K_M.gguf"
    assert veri["varsayilan"] == "gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf"
    assert veri["num_ctx"] == 4096


# --- kütüphane listeleme ------------------------------------------------------
def test_kutuphane_listele_tarama(tmp_output_base):
    from ytmcp import tools

    def _yaz(konu, uretici, dizin, baslik, tarih, puan):
        d = tmp_output_base / konu / uretici / dizin
        d.mkdir(parents=True)
        (d / "00_index.json").write_text(
            json.dumps(
                {
                    "baslik": baslik,
                    "kanal": uretici,
                    "konu": konu,
                    "analiz_tarihi": tarih,
                    "degerleme_puani": puan,
                    "video_id": dizin,
                }
            ),
            encoding="utf-8",
        )

    _yaz("hukuk", "kanal-a", "2026-06-10_v1", "Eski", "2026-06-10", 50.0)
    _yaz("genel", "kanal-b", "2026-06-14_v2", "Yeni", "2026-06-14", 80.0)
    # bozuk JSON fail-soft atlanmalı
    bozuk = tmp_output_base / "genel" / "kanal-c" / "2026-06-12_v3"
    bozuk.mkdir(parents=True)
    (bozuk / "00_index.json").write_text("{bozuk", encoding="utf-8")

    kayitlar = tools.kutuphane_listele_core()
    assert len(kayitlar) == 2  # bozuk atlandı
    assert kayitlar[0]["baslik"] == "Yeni"  # analiz_tarihi azalan sıra
    assert kayitlar[0]["konu"] == "genel" and kayitlar[0]["puan"] == 80.0
    assert kayitlar[0]["klasor"].endswith("2026-06-14_v2")


def test_kutuphane_bos_base(tmp_output_base):
    from ytmcp import tools

    assert tools.kutuphane_listele_core() == []  # ilk kullanım: hiç analiz yok


# --- yeni GUI route'ları (ASGI in-process) -----------------------------------
async def test_gui_modeller_kurulum_kutuphane_routelari(tmp_output_base, monkeypatch):
    from ytmcp.server import gui_http_app

    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": "http://tauri.localhost"},
    ) as c:
        for yol in ("/gui/modeller", "/gui/kurulum", "/gui/kutuphane"):
            r = await c.get(yol)
            assert r.status_code == 200, yol
            assert r.headers.get("access-control-allow-origin") == "http://tauri.localhost"
            pf = await c.options(yol)
            assert pf.status_code == 204


async def test_gui_ses_modeli_indir_routu(tmp_output_base, monkeypatch):
    # POST endpoint: OPTIONS preflight 204 + CORS, POST 200 + CORS (Tauri cross-origin için şart).
    # piper_hazir_mi=True → core 'zaten_var' döner (ağ YOK; threadpool sarmalama da kanıtlanır).
    from ytcore.uretim import tts
    from ytmcp.server import gui_http_app

    monkeypatch.setattr(tts, "piper_hazir_mi", lambda _d: True)
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": "http://tauri.localhost"},
    ) as c:
        pf = await c.options("/gui/ses_modeli_indir")
        assert pf.status_code == 204
        assert pf.headers.get("access-control-allow-origin") == "http://tauri.localhost"
        r = await c.post("/gui/ses_modeli_indir")
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://tauri.localhost"
        assert r.json()["durum"] == "zaten_var"


async def test_gui_dosya_guard(tmp_output_base):
    from ytmcp.server import gui_http_app

    klasor = tmp_output_base / "genel" / "kanal" / "2026-06-15_v"
    klasor.mkdir(parents=True)
    (klasor / "04_ozet-sunum.pdf").write_bytes(b"%PDF-1.4 test")
    (klasor / "00_index.json").write_text("{}", encoding="utf-8")  # liste-dışı uzantı
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": "http://tauri.localhost"},
    ) as c:
        # geçerli pdf → 200 + inline
        r = await c.get("/gui/dosya", params={"klasor": str(klasor), "ad": "04_ozet-sunum.pdf"})
        assert r.status_code == 200
        assert "application/pdf" in r.headers.get("content-type", "")
        assert "inline" in r.headers.get("content-disposition", "")
        # liste-dışı uzantı (.json) → 415
        r2 = await c.get("/gui/dosya", params={"klasor": str(klasor), "ad": "00_index.json"})
        assert r2.status_code == 415
        # output_base dışı → 403 (path-traversal guard)
        dis = str(tmp_output_base.parent)
        r3 = await c.get("/gui/dosya", params={"klasor": dis, "ad": "x.pdf"})
        assert r3.status_code in (400, 403)
        # eksik param → 400
        r4 = await c.get("/gui/dosya", params={"klasor": str(klasor)})
        assert r4.status_code == 400


async def test_gui_analiz_et_gecersiz_model_400(tmp_output_base, tmp_path, monkeypatch):
    """Allowlist dışı model → 400 (keyfi env-enjeksiyon engellenir); env kirlenmez."""
    import os

    from ytmcp.server import gui_http_app

    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    onceki = os.environ.get("YT_CEVIRI_MODEL")
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": "http://tauri.localhost"},
    ) as c:
        r = await c.post(
            "/gui/analiz_et",
            json={"url": "https://youtu.be/x", "model": "zararlı-model-yok:99b"},
        )
    assert r.status_code == 400
    assert r.json()["hata"] == "gecersiz model"
    assert os.environ.get("YT_CEVIRI_MODEL") == onceki  # env kirlenmedi


async def test_gui_analiz_et_model_override_env_restore(tmp_output_base, tmp_path, monkeypatch):
    """Geçerli model override: 8 generation env analiz boyunca set, sonra RESTORE (kirlenmez)."""
    import os

    from ytmcp import tools
    from ytmcp.server import _GENERATION_ENV, gui_http_app

    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    # allowlist'i sabitle (Ollama'ya bağımlı olma) — test modeli geçerli sayılsın
    monkeypatch.setattr(tools, "modeller_core", lambda: {"modeller": [{"ad": "testmodel:1b"}]})
    once = {k: os.environ.get(k) for k in _GENERATION_ENV}
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Origin": "http://tauri.localhost"},
    ) as c:
        r = await c.post(
            "/gui/analiz_et",
            json={"url": "https://youtu.be/x", "model": "testmodel:1b"},
        )
    assert r.status_code == 200  # hermetik fixture (FakeLLM modeli yoksayar)
    # KRİTİK: analiz sonrası tüm generation env eski hâline döndü (process-global kirlenmedi)
    assert {k: os.environ.get(k) for k in _GENERATION_ENV} == once


# --- Faz 9: Ollama Ayarlar sayfası (test + kalıcı yapılandırma) -----------------


def test_ollama_test_core_loopback_disi_reddedilir(tmp_output_base, monkeypatch):
    # KVKK: loopback olmayan host opt-in olmadan İSTEK ATMADAN reddedilir (PII sızmasın).
    monkeypatch.delenv("YT_ALLOW_REMOTE_OLLAMA", raising=False)
    from ytmcp import tools

    r = tools.ollama_test_core("http://10.0.0.5:11434")
    assert r["erisilebilir"] is False and "KVKK" in r["hata"] and r["modeller"] == []


def test_ollama_test_core_kurulu_modelleri_tespit(tmp_output_base, monkeypatch):
    # 'kurulu Ollama + modelleri tespit': sürüm + /api/tags modelleri (ağsız: httpx monkeypatch).
    from ytmcp import tools

    class _R:
        def __init__(self, j):
            self._j = j

        def raise_for_status(self): ...

        def json(self):
            return self._j

    def _get(url, **k):
        if url.endswith("/api/version"):
            return _R({"version": "0.5.4"})
        if url.endswith("/api/tags"):
            return _R({"models": [{"name": "qwen2.5:14b"}, {"name": "bge-m3"}]})
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "get", _get)
    r = tools.ollama_test_core("127.0.0.1:11434")
    assert r["erisilebilir"] is True and r["surum"] == "0.5.4"
    assert r["model_sayisi"] == 2 and "qwen2.5:14b" in r["modeller"]


def test_ayarlar_kaydet_oku_kalici(tmp_output_base, monkeypatch):
    # Ayar kaydet → oku + config etkin host'u _ayarlar.json'dan okur (env yokken).
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    from ytcore.config import get_config
    from ytmcp import tools

    assert tools.ayarlar_kaydet_core(ollama_host="127.0.0.1:11500")["durum"] == "kaydedildi"
    o = tools.ayarlar_oku_core()
    assert o["ollama_host"] == "http://127.0.0.1:11500" and o["ollama_host_kaynak"] == "ayar"
    assert get_config().ollama_host == "http://127.0.0.1:11500"  # config dosyadan okudu


def test_ayarlar_kaydet_loopback_disi_reddedilir(tmp_output_base, monkeypatch):
    # KVKK: loopback olmayan host kaydedilemez (opt-in yoksa) → _ayarlar.json kirlenmaz.
    monkeypatch.delenv("YT_ALLOW_REMOTE_OLLAMA", raising=False)
    from ytmcp import tools

    r = tools.ayarlar_kaydet_core(ollama_host="http://10.0.0.5:11434")
    assert r["durum"] == "reddedildi" and "KVKK" in r["hata"]

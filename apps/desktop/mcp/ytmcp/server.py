from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastmcp import FastMCP
from rasathane.product.api import register_routes as _register_product_routes
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ytcore.pipeline.api import kaynak_analiz_et as _core_analiz_et

from ytmcp import tools as _tools

mcp: FastMCP = FastMCP("rasathane")

# Tauri webview farklı origin'den 127.0.0.1:8765'e istek atar. Loopback tek başına
# CSRF sınırı değildir; herhangi bir web sitesi wildcard CORS ile local sidecar'ı
# çağırabilirdi. Header'lar aşağıdaki middleware tarafından yalnız allowlist origin'e eklenir.
_CORS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Rasathane-Session",
}
_GUI_ORIGINLERI = frozenset(
    {
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "rasathane://app",
        "http://127.0.0.1:4173",
        "http://localhost:4173",
    }
)


class _GuiOriginKorumasi:
    """GUI route'larında wildcard CORS ve cross-site local sidecar çağrısını engelle."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(
            ("/gui/", "/api/rasathane/", "/api/product/")
        ):
            await self.app(scope, receive, send)
            return

        origin = next(
            (
                deger.decode("latin-1")
                for anahtar, deger in scope.get("headers", [])
                if anahtar.lower() == b"origin"
            ),
            None,
        )
        if origin is not None and origin not in _GUI_ORIGINLERI:
            yanit = JSONResponse({"hata": "origin izinli degil"}, status_code=403)
            await yanit(scope, receive, send)
            return

        token = os.environ.get("RASATHANE_SESSION_TOKEN", "")
        supplied = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key.lower() == b"x-rasathane-session"
            ),
            "",
        )
        if (
            scope.get("method") != "OPTIONS"
            and token
            and not secrets.compare_digest(token, supplied)
        ):
            yanit = JSONResponse({"error": "Uygulama oturumu doğrulanamadı."}, status_code=403)
            await yanit(scope, receive, send)
            return

        async def corslu_gonder(mesaj: Message) -> None:
            if mesaj["type"] == "http.response.start" and origin is not None:
                basliklar = MutableHeaders(scope=mesaj)
                basliklar["Access-Control-Allow-Origin"] = origin
                basliklar["Access-Control-Allow-Methods"] = _CORS["Access-Control-Allow-Methods"]
                basliklar["Access-Control-Allow-Headers"] = _CORS["Access-Control-Allow-Headers"]
                basliklar.add_vary_header("Origin")
            await send(mesaj)

        await self.app(scope, receive, corslu_gonder)


def gui_http_middleware() -> list[Middleware]:
    """FastMCP HTTP app/run için tek kaynaklı GUI origin politikası."""
    return [Middleware(_GuiOriginKorumasi)]


def gui_http_app() -> Any:
    """Test ve gömülü sunucular için üretimle aynı origin korumalı ASGI app."""
    return mcp.http_app(middleware=gui_http_middleware())


def _cp_dir() -> Path:
    d = os.environ.get("YT_CHECKPOINT_DIR", "").strip()
    return Path(d) if d else (Path.home() / ".ytanaliz")


def _bool(v: object) -> bool:
    """asr_izin string-truthiness tuzağını kapat: 'false'/'0' True olmasın (JSON gövdesi
    bazen string taşır). Yalnız açık olumlu değerler True (sessiz ASR açılması = fail-closed)."""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "evet", "yes", "on")
    return bool(v)


# Faz 7: model override — tek "üretim modeli" seçimi 8 generation env'ini AYNI değere set
# eder. embedding (bge-m3) + NER (bert ayrı proses) DOKUNULMAZ (RAG/index + PII-gate sabit).
_GENERATION_ENV = (
    "YT_CEVIRI_MODEL",
    "YT_MAP_MODEL",
    "YT_REDUCE_MODEL",
    "YT_JUDGE_MODEL",
    "YT_CLAIM_MODEL",
    "YT_VERDICT_MODEL",
    "YT_MEMORY_MODEL",
    "YT_HARITA_MODEL",
)


def _generation_modelleri() -> set[str]:
    """Allowlist: /gui/modeller'in döndürdüğü generation modeli adları (keyfi env-enjeksiyon
    yok). Ollama erişilemezse boş set → override reddedilir (varsayılan modelle devam)."""
    try:
        return {str(m.get("ad", "")) for m in _tools.modeller_core().get("modeller", [])}
    except Exception:  # noqa: BLE001 — durum sorgusu kritik yol değil
        return set()


def analiz_et_core(url: str, konu: str, thread_id: str, asr_izin: bool = False) -> dict[str, Any]:
    """GUI ve MCP tool'unun ORTAK çağırdığı çekirdek (DoD #10: GUI=MCP aynı sonuç)."""
    sonuc = _core_analiz_et(
        url=url, konu=konu, thread_id=thread_id, checkpoint_dir=_cp_dir(), asr_izin=asr_izin
    )
    return sonuc.model_dump()


@mcp.tool
def health() -> dict[str, Any]:
    """Sunucu sağlık kontrolü."""
    return {"durum": "ok", "servis": "rasathane", "faz": 5}


@mcp.tool
def kaynak_analiz_et(
    url: str, konu: str = "genel", thread_id: str = "varsayilan", asr_izin: bool = False
) -> dict[str, Any]:
    """Desteklenen bir URL'yi UÇTAN UCA analiz eder (edinim → çeviri → döküm → özet →
    değerleme → kişisel analiz → fact-check → zihin haritası → seslendirme + indeks).

    YouTube, GitHub, arXiv, Reddit, Hugging Face ve public web sayfalarını otomatik tanır.
    Reddit gerçek edinimi onaylı OAuth tokenı ister. asr_izin yalnız YouTube için kullanılır.
    """
    return analiz_et_core(url, konu, thread_id, asr_izin)


@mcp.tool
def analiz_et(
    url: str, konu: str = "genel", thread_id: str = "varsayilan", asr_izin: bool = False
) -> dict[str, Any]:
    """Geriye uyumlu tam analiz adı; yeni entegrasyonlarda `kaynak_analiz_et` tercih edilir."""
    return kaynak_analiz_et(url, konu, thread_id, asr_izin)


# --- Faz 5 adım-tool'ları (Mod A): senkron + stateless + JSON; host LLM zincirler. ---


@mcp.tool
def transcript_al(url: str, asr_izin: bool = False) -> dict[str, Any]:
    """YouTube videosundan transkript çeker (altyazı-önce; asr_izin=True → yerel Whisper).

    Tam analiz yerine yalnız ham transkript metni gerektiğinde kullan."""
    return _tools.transcript_al_core(url, asr_izin)


@mcp.tool
def cevir(metin: str) -> dict[str, Any]:
    """Metni hukuk-glossary kısıtıyla Türkçeye çevirir (yerel model — KVKK güvenli).

    Yabancı dildeki transkript/metni Türkçe çalışma metnine dönüştürmek için kullan."""
    return _tools.cevir_core(metin)


@mcp.tool
def ozetle(metin: str) -> dict[str, Any]:
    """Türkçe metinden kısa + detaylı özet üretir (map-reduce, yerel model).

    Uzun transkript/dökümden özet gerektiğinde kullan; çıktı: {kisa, detay}."""
    return _tools.ozetle_core(metin)


@mcp.tool
def dokum_cikar(metin: str) -> dict[str, Any]:
    """Türkçe metni kronolojik bölümlere ayırır (segment + keyword + başlık).

    Videonun konu-akışını bölüm bölüm görmek gerektiğinde kullan."""
    return _tools.dokum_cikar_core(metin)


@mcp.tool
def degerlendir(metin: str, konu: str = "genel", baslik: str = "") -> dict[str, Any]:
    """İçeriğin BilgiDeğeri puanını (0-100) ve şeffaf faktörlerini hesaplar
    (novelty/rarity/niş/recency/length — geçmiş analiz korpusuna göre).

    İçeriğin nadir/niş/yeni olup olmadığını ölçmek için kullan."""
    return _tools.degerlendir_core(metin, konu, baslik)


@mcp.tool
def fact_check(metin: str) -> dict[str, Any]:
    """Metindeki olgusal iddiaları çıkarır ve web kanıtıyla denetler (KVKK: sorgular
    anonimleştirilir; PII/kişi-adı içeren iddia web'e GİTMEZ; anahtarsız 'web_yok').

    İçerikteki iddiaların doğruluk denetimi gerektiğinde kullan."""
    return _tools.fact_check_core(metin)


@mcp.tool
def zihin_haritasi(
    metin: str, konu: str = "genel", html_dosya: str | None = None
) -> dict[str, Any]:
    """İçerikten zihin haritası ağacı üretir (JSON düğüm ağacı; html_dosya verilirse
    offline interaktif markmap HTML'i o yola yazılır — HTML string döndürülmez).

    Kavram haritası / yapılandırılmış genel bakış gerektiğinde kullan."""
    return _tools.zihin_haritasi_core(metin, konu, html_dosya)


@mcp.tool
def seslendir(metin: str, hedef_dosya: str | None = None) -> dict[str, Any]:
    """Metni seslendirir (KVKK kararı: PII/kişi-adı → yalnız yerel Piper; cloud yalnız
    PII-temiz + bilinçli opt-in + anahtar). Ses dosyasının yolunu döndürür.

    Özetin sesli sürümü gerektiğinde kullan."""
    return _tools.seslendir_core(metin, hedef_dosya)


@mcp.tool
def indeks_ara(sorgu: str, k: int = 5) -> dict[str, Any]:
    """Geçmiş video analizlerinde hibrit arama yapar (anlamsal + keyword, RRF birleşik).

    'Daha önce bu konuda ne analiz edilmişti?' sorusunda kullan."""
    return _tools.indeks_ara_core(sorgu, k)


@mcp.tool
def kurulum_kontrol() -> dict[str, Any]:
    """Sistem hazırlık durumunu raporlar: Ollama erişimi, Piper voice, anahtar VARLIĞI
    (anahtarın kendisi asla dönmez), opt-in bayrakları, çıktı kökü.

    Kurulum/sorun-giderme ve bootstrap sihirbazı için kullan."""
    return _tools.kurulum_kontrol_core()


@mcp.tool
def ses_modeli_indir() -> dict[str, Any]:
    """Piper TR voice modelini (tr_TR-dfki-medium) HuggingFace'den indirir — sesli özet için
    bir kerelik kurulum. KVKK: yalnız MODEL indirir (kullanıcı/video verisi egress YOK).

    Sesli özet 'ses_modeli_yok' verdiğinde kullan."""
    return _tools.ses_modeli_indir_core()


@mcp.custom_route("/gui/analiz_et", methods=["POST", "OPTIONS"])
async def gui_analiz_et(request: Request) -> Response:
    if request.method == "OPTIONS":  # CORS preflight
        return Response(status_code=204, headers=_CORS)
    # Girdi doğrulama (denetim MED): bozuk/eksik gövde CORS'suz 500'e düşmesin → düzgün 400.
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — geçersiz JSON
        return JSONResponse({"hata": "gecersiz JSON govdesi"}, status_code=400, headers=_CORS)
    url = (body or {}).get("url", "") if isinstance(body, dict) else ""
    if not isinstance(url, str) or not url.strip():
        return JSONResponse({"hata": "url zorunlu"}, status_code=400, headers=_CORS)
    # Faz 7 model override (opsiyonel): body.model gelirse 8 generation env'ini o modele set
    # et, analiz sonrası finally'de RESTORE. Allowlist (/gui/modeller) — keyfi env-enjeksiyon yok.
    model = body.get("model") if isinstance(body, dict) else None
    if model:
        if not isinstance(model, str) or model not in _generation_modelleri():
            return JSONResponse({"hata": "gecersiz model"}, status_code=400, headers=_CORS)

    def _override_ile_analiz() -> dict[str, Any]:
        from ytcore.pipeline.api import ANALYSIS_LOCK

        # Legacy model seçimi de yeni ürün worker'ıyla aynı mutex'te snapshot edilir.
        with ANALYSIS_LOCK:
            yedek = {k: os.environ.get(k) for k in _GENERATION_ENV} if model else {}
            try:
                if isinstance(model, str):
                    for k in yedek:
                        os.environ[k] = model
                return analiz_et_core(
                    url,
                    body.get("konu", "genel"),
                    body.get("thread_id", "gui"),
                    _bool(body.get("asr_izin", False)),
                )
            finally:
                for k, v in yedek.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    # Çok-dakikalık senkron pipeline'ı event loop DIŞINDA koş (denetim HIGH): aksi hâlde
    # analiz sürerken /gui/health + CORS preflight + TÜM MCP HTTP trafiği donar.
    try:
        sonuc = await run_in_threadpool(_override_ile_analiz)
    except Exception as e:  # noqa: BLE001 — hata CORS'lu dönmeli (webview 'Failed to fetch' yerine mesaj)
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:300]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(sonuc, headers=_CORS)


@mcp.custom_route("/gui/health", methods=["GET", "OPTIONS"])
async def gui_health(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    return JSONResponse({"durum": "ok"}, headers=_CORS)


def _klasor_ac_sync(hedef: Path) -> None:
    """Doğrulanmış klasörü platform dosya yöneticisinde aç. shell=True ASLA; arg listesi geçilir.

    path daima resolve()+is_relative_to ile output_base'e sınırlandıktan SONRA gelir
    (komut-enjeksiyon yok)."""
    if sys.platform == "win32":
        os.startfile(str(hedef))  # sys.platform guard'ı mypy'da daraltır (win32-only API)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(hedef)], check=False)
    else:
        subprocess.run(["xdg-open", str(hedef)], check=False)


@mcp.custom_route("/gui/klasor_ac", methods=["POST", "OPTIONS"])
async def gui_klasor_ac(request: Request) -> Response:
    """Analiz çıktı klasörünü Explorer'da açar (GUI 'Klasörü Aç'). KVKK/güvenlik: YALNIZ
    output_base ALTINDAKİ gerçek bir klasör — path-traversal/sembolik-link kaçışı resolve ile
    çözülür (is_relative_to, py3.9+). Çıktı kökü dışı → 403; yok → 400."""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — geçersiz JSON
        return JSONResponse({"hata": "gecersiz JSON govdesi"}, status_code=400, headers=_CORS)
    klasor = (body or {}).get("klasor", "") if isinstance(body, dict) else ""
    if not isinstance(klasor, str) or not klasor.strip():
        return JSONResponse({"hata": "klasor zorunlu"}, status_code=400, headers=_CORS)

    from ytcore.config import get_config

    base = get_config().output_base.resolve()
    try:
        hedef = Path(klasor).resolve(strict=True)  # strict: yoksa FileNotFoundError
    except (OSError, RuntimeError, ValueError):
        return JSONResponse({"hata": "klasor bulunamadi"}, status_code=400, headers=_CORS)
    if not hedef.is_relative_to(base):
        return JSONResponse(
            {"hata": "izin yok: cikti kokunun disinda"}, status_code=403, headers=_CORS
        )
    if not hedef.is_dir():
        return JSONResponse({"hata": "klasor degil"}, status_code=400, headers=_CORS)
    try:
        await run_in_threadpool(_klasor_ac_sync, hedef)
    except Exception as e:  # noqa: BLE001 — açma ham hatası CORS'lu dönmeli (webview mesaj gösterir)
        return JSONResponse(
            {"hata": f"klasor acilamadi: {type(e).__name__}"}, status_code=500, headers=_CORS
        )
    return JSONResponse({"durum": "acildi"}, headers=_CORS)


# --- Faz 7: model listesi · kurulum durumu · kütüphane · dosya görüntüleme ---


@mcp.tool
def modeller() -> dict[str, Any]:
    """Yüklü Ollama generation modellerini (embedding hariç) tahmini VRAM + durumla listele."""
    return _tools.modeller_core()


@mcp.tool
def kutuphane_listele() -> dict[str, Any]:
    """Geçmiş analizleri listele (output_base 00_index.json taraması; GUI=MCP simetri)."""
    return {"kayitlar": _tools.kutuphane_listele_core()}


@mcp.custom_route("/gui/modeller", methods=["GET", "OPTIONS"])
async def gui_modeller(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        veri = await run_in_threadpool(_tools.modeller_core)
    except Exception as e:  # noqa: BLE001 — CORS'lu hata
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(veri, headers=_CORS)


@mcp.custom_route("/gui/kurulum", methods=["GET", "OPTIONS"])
async def gui_kurulum(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        veri = await run_in_threadpool(_tools.kurulum_kontrol_core)
    except Exception as e:  # noqa: BLE001 — CORS'lu hata (config loopback ValueError dahil)
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(veri, headers=_CORS)


@mcp.custom_route("/gui/ses_modeli_indir", methods=["POST", "OPTIONS"])
async def gui_ses_modeli_indir(request: Request) -> Response:
    """Piper TR voice modelini indirir (GUI 'Ses modelini indir' butonu). POST: yan etki var
    (ağdan ~60MB MODEL çeker — kullanıcı/video verisi egress YOK, KVKK güvenli). Threadpool:
    indirme bloklamasın diye event-loop'tan ayrı koşar."""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        veri = await run_in_threadpool(_tools.ses_modeli_indir_core)
    except Exception as e:  # noqa: BLE001 — CORS'lu hata (webview mesaj gösterir)
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(veri, headers=_CORS)


@mcp.custom_route("/gui/ollama_test", methods=["POST", "OPTIONS"])
async def gui_ollama_test(request: Request) -> Response:
    """GUI Ayarlar 'Test Et': gövdedeki host'u (yoksa mevcut) test eder + yüklü modelleri tespit.
    KVKK: loopback olmayan host opt-in olmadan reddedilir (ollama_test_core içinde)."""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — geçersiz JSON → mevcut host'u test et
        body = {}
    host = (body or {}).get("host") if isinstance(body, dict) else None
    try:
        veri = await run_in_threadpool(_tools.ollama_test_core, host)
    except Exception as e:  # noqa: BLE001 — CORS'lu hata
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(veri, headers=_CORS)


@mcp.custom_route("/gui/ayarlar", methods=["GET", "POST", "OPTIONS"])
async def gui_ayarlar(request: Request) -> Response:
    """GUI Ayarlar: GET → mevcut/kalıcı ayarlar; POST {ollama_host} → kaydet (KVKK guard'lı)."""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        if request.method == "GET":
            veri = await run_in_threadpool(_tools.ayarlar_oku_core)
        else:
            body = await request.json()
            b = body if isinstance(body, dict) else {}
            if os.environ.get("RASATHANE_SESSION_TOKEN") and b.get("motor_kok"):
                return JSONResponse(
                    {"hata": "Kurulu uygulamada motor konumu arayüzden değiştirilemez."},
                    status_code=403,
                    headers=_CORS,
                )
            veri = await run_in_threadpool(
                _tools.ayarlar_kaydet_core, b.get("ollama_host"), b.get("motor_kok")
            )
    except Exception as e:  # noqa: BLE001 — CORS'lu hata (config loopback ValueError dahil)
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(veri, headers=_CORS)


@mcp.custom_route("/gui/kutuphane", methods=["GET", "OPTIONS"])
async def gui_kutuphane(request: Request) -> Response:
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    try:
        veri = await run_in_threadpool(_tools.kutuphane_listele_core)
    except Exception as e:  # noqa: BLE001 — CORS'lu hata (config OLLAMA_HOST loopback ValueError dahil)
        return JSONResponse(
            {"hata": f"{type(e).__name__}: {str(e)[:200]}"}, status_code=500, headers=_CORS
        )
    return JSONResponse(veri, headers=_CORS)


_GORUNTULENEBILIR = {".pdf", ".html"}


@mcp.custom_route("/gui/dosya", methods=["GET", "OPTIONS"])
async def gui_dosya(request: Request) -> Response:
    """Çıktı dosyasını WebView'a stream eder (PDF/HTML görüntüleyici modal). KVKK/güvenlik:
    YALNIZ output_base altı + beyaz-liste uzantı (klasor_ac ile aynı resolve+is_relative_to
    guard). Salt-okunur → egress yok (NER/anonim gate gerekmez). 'ad' path-ayracı içerse bile
    resolve+is_relative_to traversal'ı keser."""
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS)
    klasor = request.query_params.get("klasor", "")
    ad = request.query_params.get("ad", "")
    if not klasor or not ad:
        return JSONResponse({"hata": "klasor+ad zorunlu"}, status_code=400, headers=_CORS)
    if ad in {".", ".."} or "/" in ad or "\\" in ad or Path(ad).name != ad:
        return JSONResponse(
            {"hata": "yalnız dosya adı kullanılabilir"}, status_code=400, headers=_CORS
        )

    from ytcore.config import get_config

    base = get_config().output_base.resolve()
    try:
        hedef = (Path(klasor) / ad).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return JSONResponse({"hata": "dosya bulunamadi"}, status_code=400, headers=_CORS)
    if not hedef.is_file():
        return JSONResponse({"hata": "dosya degil"}, status_code=400, headers=_CORS)
    if hedef.suffix.lower() not in _GORUNTULENEBILIR:
        return JSONResponse({"hata": "desteklenmeyen tur"}, status_code=415, headers=_CORS)
    media = "application/pdf" if hedef.suffix.lower() == ".pdf" else "text/html; charset=utf-8"
    if not hedef.is_relative_to(base):
        from rasathane.product.api import get_service
        from rasathane.product.artifacts import recorded_preview

        content = await run_in_threadpool(recorded_preview, get_service().store, Path(klasor) / ad)
        if content is None:
            return JSONResponse(
                {"hata": "izin yok: kayıtlı çıktı doğrulanamadı"}, status_code=403, headers=_CORS
            )
        return Response(
            content,
            media_type=media,
            headers={
                **_CORS,
                "Content-Disposition": f"inline; filename*=utf-8''{quote(hedef.name)}",
            },
        )
    # filename ŞART: Starlette FileResponse, filename yoksa Content-Disposition yazmaz →
    # 'inline' düşmez, tarayıcı indirmeye düşebilir. filename + inline = viewer'da açılır.
    return FileResponse(
        str(hedef),
        headers=_CORS,
        media_type=media,
        filename=hedef.name,
        content_disposition_type="inline",
    )


# Tek ürün API'si aynı ASGI origin/session sınırını kullanır. Import side-effect'i
# veri yaratmaz veya worker başlatmaz; ProductService ilk ürün isteğinde kurulur.
_register_product_routes(mcp)

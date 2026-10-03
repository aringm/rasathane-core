from __future__ import annotations

from pathlib import Path

import httpx
from ytmcp.server import gui_http_app


async def test_gui_route_cors_ve_transkript_sonuc(tmp_output_base, tmp_path, monkeypatch):
    """In-process ASGI: GUI route + CORS (Tauri webview cross-origin) + Faz 1 transkript.

    Sidecar spawn etmeden FastMCP http app'i httpx ASGITransport ile test eder
    (deterministik, CI-uyumlu). Adversarial review #7 (CORS) + 'GUI route test yok' MED.
    """
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    transport = httpx.ASGITransport(app=gui_http_app())
    origin = {"Origin": "http://tauri.localhost"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        h = await c.get("/gui/health", headers=origin)
        assert h.status_code == 200
        assert h.json()["durum"] == "ok"
        assert h.headers.get("access-control-allow-origin") == "http://tauri.localhost"

        pf = await c.options("/gui/analiz_et", headers=origin)
        assert pf.status_code == 204
        assert pf.headers.get("access-control-allow-origin") == "http://tauri.localhost"

        r = await c.post(
            "/gui/analiz_et",
            json={"url": "https://youtu.be/cors", "konu": "genel"},
            headers=origin,
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://tauri.localhost"
        d = r.json()
        # Faz 1: fixture-clean (autouse) altyazı → gerçek transkript (stub=False)
        assert d["stub"] is False
        assert d["transkript_durumu"] == "altyazi"
        assert d["cloud_cagrisi_sayisi"] == 0


async def test_gui_origin_allowlist_bilinmeyen_siteyi_reddeder():
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        kotu_origin = {"Origin": "https://ornek-saldirgan.test"}
        preflight = await c.options("/gui/analiz_et", headers=kotu_origin)
        assert preflight.status_code == 403
        assert "access-control-allow-origin" not in preflight.headers

        istek = await c.post(
            "/gui/analiz_et",
            json={"url": "https://github.com/openai/openai-python"},
            headers=kotu_origin,
        )
        assert istek.status_code == 403
        assert "access-control-allow-origin" not in istek.headers

        # Native/CLI istemcileri Origin göndermez; loopback API erişimi korunur.
        native = await c.get("/gui/health")
        assert native.status_code == 200
        assert "access-control-allow-origin" not in native.headers


async def test_gui_origin_allowlist_electron_ozel_protokolunu_kabul_eder():
    transport = httpx.ASGITransport(app=gui_http_app())
    origin = {"Origin": "rasathane://app"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        preflight = await c.options("/gui/analiz_et", headers=origin)
        assert preflight.status_code == 204
        assert preflight.headers.get("access-control-allow-origin") == "rasathane://app"
        health = await c.get("/gui/health", headers=origin)
        assert health.status_code == 200
        assert health.headers.get("access-control-allow-origin") == "rasathane://app"


async def test_gui_route_github_fixture_ortak_kaynak_hattini_kullanir(
    tmp_output_base, tmp_path, monkeypatch
):
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path / "checkpoints"))
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/gui/analiz_et",
            json={
                "url": "https://github.com/openai/openai-python",
                "konu": "genel",
                "thread_id": "gui-github-fixture",
            },
            headers={"Origin": "http://tauri.localhost"},
        )

    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://tauri.localhost"
    sonuc = r.json()
    assert sonuc["stub"] is False
    assert sonuc["kaynak_turu"] == "github"
    assert sonuc["kaynak_durumu"] == "fixture"
    assert sonuc["transkript_durumu"] == "kaynak"
    assert sonuc["index"]["kaynak_turu"] == "github"
    assert sonuc["index"]["kaynak_url"].startswith("https://github.com/")
    assert (Path(sonuc["klasor"]) / "01_kaynak-icerigi.md").is_file()


async def test_gui_route_gecersiz_govde_400_corslu(tmp_output_base, tmp_path, monkeypatch):
    # denetim MED: eksik/bozuk gövde CORS'suz 500'e düşmemeli → 400 + CORS header.
    monkeypatch.setenv("YT_CHECKPOINT_DIR", str(tmp_path))
    transport = httpx.ASGITransport(app=gui_http_app())
    origin = {"Origin": "http://tauri.localhost"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # url yok
        r1 = await c.post("/gui/analiz_et", json={"konu": "genel"}, headers=origin)
        assert r1.status_code == 400
        assert r1.headers.get("access-control-allow-origin") == "http://tauri.localhost"
        # bozuk JSON
        r2 = await c.post(
            "/gui/analiz_et",
            content=b"{bozuk",
            headers={"Content-Type": "application/json", **origin},
        )
        assert r2.status_code == 400
        assert r2.headers.get("access-control-allow-origin") == "http://tauri.localhost"


async def test_gui_klasor_ac_guard(tmp_output_base, monkeypatch):
    """KVKK/güvenlik: /gui/klasor_ac YALNIZ output_base altındaki gerçek klasörü açar.

    path-traversal (üst dizin) -> 403, var-olmayan -> 400, eksik govde -> 400, geçerli -> 200.
    _klasor_ac_sync mock'lanır (gerçek Explorer açılmaz; CI-uyumlu). Guard sökülürse 403/400
    testleri kırmızı döner (mutasyon-kontrol)."""
    import ytmcp.server as srv

    acilanlar: list = []
    monkeypatch.setattr(srv, "_klasor_ac_sync", lambda h: acilanlar.append(h))
    base = tmp_output_base  # fixture YT_OUTPUT_BASE'i buraya set etti
    gecerli = base / "kanal" / "video-abc"
    gecerli.mkdir(parents=True)
    transport = httpx.ASGITransport(app=gui_http_app())
    origin = {"Origin": "http://tauri.localhost"}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # geçerli alt-klasör -> 200 + acildi + CORS + gerçekten _klasor_ac_sync çağrıldı
        r = await c.post("/gui/klasor_ac", json={"klasor": str(gecerli)}, headers=origin)
        assert r.status_code == 200 and r.json()["durum"] == "acildi"
        assert r.headers.get("access-control-allow-origin") == "http://tauri.localhost"
        assert len(acilanlar) == 1
        # output_base DIŞI (üst dizin) -> 403 (path-traversal guard)
        r2 = await c.post("/gui/klasor_ac", json={"klasor": str(base.parent)}, headers=origin)
        assert r2.status_code == 403
        # var-olmayan -> 400
        r3 = await c.post(
            "/gui/klasor_ac", json={"klasor": str(base / "yok-klasor")}, headers=origin
        )
        assert r3.status_code == 400
        # eksik klasor -> 400
        r4 = await c.post("/gui/klasor_ac", json={}, headers=origin)
        assert r4.status_code == 400
        # OPTIONS preflight -> 204 + CORS
        pf = await c.options("/gui/klasor_ac", headers=origin)
        assert pf.status_code == 204
        assert pf.headers.get("access-control-allow-origin") == "http://tauri.localhost"
    # 403/400 yolları _klasor_ac_sync'i ASLA çağırmadı (yalnız doğrulanmış path açılır)
    assert len(acilanlar) == 1

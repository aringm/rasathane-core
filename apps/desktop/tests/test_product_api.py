from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from rasathane.product import api
from rasathane.product.connectors import muhakeme_configured, set_service_session
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore
from ytmcp.server import gui_http_app


@pytest.fixture
def service(tmp_path, monkeypatch):
    service = ProductService(ProductStore(tmp_path), autostart=False)
    monkeypatch.setattr(api, "_service", service)
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("RASATHANE_MUHAKEME_API_TOKEN", raising=False)
    monkeypatch.delenv("RASATHANE_MUHAKEME_API_URL", raising=False)
    set_service_session(None)
    yield service
    set_service_session(None)


async def test_user_flow_workspace_note_search_export(service):
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(
        transport=transport, base_url="http://localhost", headers={"Origin": "rasathane://app"}
    ) as client:
        empty = await client.get("/api/rasathane/state")
        assert empty.status_code == 200
        assert empty.json()["counts"]["articles"] == 0
        workspace = (
            await client.post("/api/rasathane/workspaces", json={"name": "İş hukuku"})
        ).json()
        note = await client.post(
            "/api/rasathane/notes",
            json={"workspace_id": workspace["id"], "title": "Kıdem", "body": "İşçilik alacağı"},
        )
        assert note.status_code == 201
        queued = await client.post(
            "/api/rasathane/research",
            json={"query": "iscilik", "workspace_id": workspace["id"], "web": False},
        )
        assert queued.status_code == 202
        service.run_once()
        job = (await client.get("/api/rasathane/jobs/" + queued.json()["id"])).json()
        assert job["status"] == "completed"
        assert job["result"]["local_results"][0]["title"] == "Kıdem"
        exported = await client.get(
            "/api/rasathane/export", params={"workspace_id": workspace["id"]}
        )
        assert exported.json()["notes"][0]["body"] == "İşçilik alacağı"
        assert "attachment" in exported.headers["content-disposition"]


async def test_topic_detail_restores_latest_completed_result_outside_recent_jobs(service):
    store = service.store
    topic = store.create_topic("İş hukuku", "işçilik alacağı")
    path = "/api/rasathane/topics/" + topic["id"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        assert (await client.get(path)).json() == {"topic": topic, "latest_result": None}
        assert (await client.get("/api/rasathane/topics/olmayan")).status_code == 404
        old = store.enqueue("refresh", {"topic_id": topic["id"]})
        store.update_job(old["id"], "completed", result={"web_results": []})
        latest = store.enqueue("refresh", {"topic_id": topic["id"]})
        expected = {
            "web_results": [{"url": "https://example.org/karar", "title": "Karar"}],
            "new_count": 1,
        }
        store.update_job(latest["id"], "completed", result=expected)
        failed = store.enqueue("refresh", {"topic_id": topic["id"]})
        store.update_job(failed["id"], "failed", error="Kaynak erişilemedi.")
        for _ in range(101):
            unrelated = store.enqueue("refresh", {"topic_id": "other-topic"})
            store.update_job(unrelated["id"], "completed", result={"web_results": []})
        assert latest["id"] not in {job["id"] for job in store.list_jobs()}
        response = await client.get(path)
        assert response.status_code == 200
        assert response.json() == {"topic": topic, "latest_result": expected}


async def test_analysis_user_flow_executes_full_public_engine_and_persists_artifacts(
    service, tmp_output_base
):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        response = await client.post(
            "/api/rasathane/analysis",
            json={
                "url": "https://youtu.be/product-api-flow",
                "konu": "hukuk",
                "asr_izin": False,
            },
        )
        assert response.status_code == 202
        service.run_once()
        job = (await client.get("/api/rasathane/jobs/" + response.json()["id"])).json()
        assert job["status"] == "completed"
        result = job["result"]
        assert Path(result["klasor"]).name.endswith(job["id"])
        assert result["ozet_detay"] and result["stub"] is False
        assert "factcheck_iddialar" in result and "cloud_cagrisi_sayisi" in result
        assert result["artifacts"]
        assert any(item["name"] == "03_dokum.docx" for item in result["artifacts"])
        assert all(len(item["sha256"]) == 64 for item in result["artifacts"])
        state = (await client.get("/api/rasathane/state")).json()
        assert state["counts"]["library"] == 1
        assert "engine_result" not in state["library"][0]["provenance"]
        assert state["jobs"][0]["result"] is None and state["jobs"][0]["has_result"] is True
        assert job["has_result"] is True
        assert service.store.library()[0]["provenance"]["engine_result"] == result


async def test_large_results_are_lazy_and_full_export_is_preserved(service):
    result = {"ozet_detay": "gerçek uzun analiz " * 200_000, "all_fields": [1, 2, 3]}
    job = service.store.enqueue("analysis", {"url": "https://example.org/report"})
    service.store.update_job(job["id"], "completed", result=result)
    service.store.add_analysis(job["id"], result)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()),
        base_url="http://localhost",
        headers={"Origin": "rasathane://app"},
    ) as client:
        state = await client.get("/api/rasathane/state")
        assert len(state.content) < 20_000
        assert state.json()["library"][0]["body_truncated"] is True
        listed = (await client.get("/api/rasathane/jobs")).json()["items"][0]
        assert listed["result"] is None and listed["has_result"] is True
        restored = (await client.get("/api/rasathane/jobs/" + job["id"])).json()
        assert restored["result"] == result
        assert (await client.get("/api/rasathane/export")).json()["jobs"][0]["result"] == result
    assert "engine_result" not in service.store.search("gercek")[0]["provenance"]


async def test_native_service_token_requires_session_never_persists_or_exports(
    service, monkeypatch
):
    token = "at_" + "A" * 43
    path = "/api/product/service-session"
    transport = httpx.ASGITransport(app=gui_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.post(path, json={"access_token": token})).status_code == 403
        monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "test-session-secret")
        assert (await client.post(path, json={"access_token": token})).status_code == 403
        assert (
            await client.post(
                path,
                json={"access_token": token},
                headers={
                    "Origin": "https://evil.example",
                    "X-Rasathane-Session": "test-session-secret",
                },
            )
        ).status_code == 403
        headers = {"Origin": "rasathane://app", "X-Rasathane-Session": "test-session-secret"}
        response = await client.post(path, json={"access_token": token}, headers=headers)
        assert response.status_code == 200 and response.json() == {"configured": True}
        assert muhakeme_configured()
        exported = await client.get("/api/rasathane/export", headers=headers)
        assert token not in exported.text
        assert token not in (await client.get("/api/rasathane/state", headers=headers)).text
        for file in service.store.directory.glob("*.sqlite3*"):
            assert token.encode() not in file.read_bytes()
        assert (
            await client.post(path, json={"access_token": "bad"}, headers=headers)
        ).status_code == 422
        cleared = await client.post(path, json={"access_token": None}, headers=headers)
        assert cleared.json() == {"configured": False}
        assert not muhakeme_configured()


async def test_product_and_legacy_session_and_origin_guard(service, monkeypatch):
    monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "test-session-secret")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        for path in ("/api/rasathane/state", "/gui/health"):
            assert (await client.get(path)).status_code == 403
            assert (
                await client.get(
                    path,
                    headers={
                        "Origin": "https://evil.example",
                        "X-Rasathane-Session": "test-session-secret",
                    },
                )
            ).status_code == 403
            assert (
                await client.get(
                    path,
                    headers={
                        "Origin": "rasathane://app",
                        "X-Rasathane-Session": "test-session-secret",
                    },
                )
            ).status_code == 200
        preflight = await client.options(
            "/api/rasathane/state", headers={"Origin": "rasathane://app"}
        )
        assert preflight.status_code == 204
        assert "X-Rasathane-Session" in preflight.headers["Access-Control-Allow-Headers"]
        denied = await client.post(
            "/gui/ayarlar",
            json={"motor_kok": "C:/evil"},
            headers={"Origin": "rasathane://app", "X-Rasathane-Session": "test-session-secret"},
        )
        assert denied.status_code == 403


async def test_validation_rejects_ssrf_unknown_settings_and_string_bool(service):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        assert (
            await client.post("/api/rasathane/analysis", json={"url": "http://127.0.0.1/private"})
        ).status_code == 400
        assert (
            await client.post(
                "/api/rasathane/analysis", json={"url": "https://example.com", "asr_izin": "false"}
            )
        ).status_code == 422
        assert (
            await client.post("/api/rasathane/settings", json={"output_dir": "C:/Windows"})
        ).status_code == 422
        assert (
            await client.post("/api/rasathane/settings", json={"topic_refresh_minutes": 1})
        ).status_code == 400
        assert (
            await client.post(
                "/api/rasathane/research",
                content='{"query":"x"}',
                headers={"content-type": "text/plain"},
            )
        ).status_code == 400

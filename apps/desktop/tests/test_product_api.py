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


async def test_retired_features_are_unreachable_but_archive_and_research_survive(service):
    store = service.store
    workspace = store.create_workspace("Eski iş hukuku")
    store.save_note(workspace["id"], "Kıdem", "İşçilik alacağı")
    topic = store.create_topic("Eski konu", "işçilik")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        state = (await client.get("/api/rasathane/state")).json()
        assert not {"workspaces", "topics"} & state.keys()
        assert not {"workspaces", "topics", "notes"} & state["counts"].keys()
        for resource in ("workspaces", "notes", "topics"):
            assert (await client.get(f"/api/rasathane/{resource}")).status_code == 404
            assert (await client.post(f"/api/rasathane/{resource}", json={})).status_code == 404
        for suffix in ("", "/refresh"):
            path = f"/api/rasathane/topics/{topic['id']}{suffix}"
            response = await (client.post(path, json={}) if suffix else client.get(path))
            assert response.status_code == 404
        for path, body in (
            ("research", {"query": "iscilik", "workspace_id": workspace["id"]}),
            ("bulletins", {"article_ids": ["one"], "workspace_id": workspace["id"]}),
            ("settings", {"topic_refresh_minutes": 180}),
            ("agenda-profile", {"include_topics": True}),
            ("agenda-profile", {"workspace_ids": []}),
        ):
            assert (await client.post(f"/api/rasathane/{path}", json=body)).status_code == 422
        for path in ("export", "conversations"):
            assert (await client.get(f"/api/rasathane/{path}?workspace_id=old")).status_code == 400
        queued = await client.post(
            "/api/rasathane/research", json={"query": "iscilik", "web": False}
        )
        assert queued.status_code == 202
        assert "workspace_id" not in queued.json()["request"]
        assert service.run_once()
        job = (await client.get("/api/rasathane/jobs/" + queued.json()["id"])).json()
        assert job["status"] == "completed"
        assert job["result"]["local_results"][0]["title"] == "Kıdem"
        exported = await client.get("/api/rasathane/export")
        assert exported.json()["notes"][0]["body"] == "İşçilik alacağı"
        assert exported.json()["workspaces"][0] == workspace
        assert exported.json()["topics"][0] == topic
        assert "attachment" in exported.headers["content-disposition"]


async def test_source_management_and_archive_filters(service):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/api/rasathane/sources",
            json={"name": "Hukuk", "url": "https://example.org/feed", "category": "turk_hukuku"},
        )
        assert response.status_code == 201
        source = response.json()
        path = f"/api/rasathane/sources/{source['id']}/update"
        paused = await client.post(path, json={"enabled": False})
        assert paused.status_code == 200 and paused.json()["enabled"] is False
        assert paused.json()["category"] == "turk_hukuku"
        edited = await client.post(
            path, json={"name": "Düzenlenen", "url": "https://example.org/new"}
        )
        assert edited.status_code == 200 and edited.json()["id"] == source["id"]
        assert (await client.post(path, json={"enabled": "false"})).status_code == 422
        assert (await client.post(path, json={"metadata": {"token": "test"}})).status_code == 422
        assert (await client.post(path, json={"url": "http://127.0.0.1/"})).status_code == 400
        assert (await client.post(path, json={"name": " "})).status_code == 400
        service.store.add_articles(
            source["id"], [{"title": "İşçilik", "url": "https://example.org/1"}]
        )
        result = await client.get(
            "/api/rasathane/articles",
            params={
                "source_id": source["id"],
                "category": "turk_hukuku",
                "query": "iscilik",
                "limit": 1,
            },
        )
        assert result.status_code == 200 and result.json()["total"] == 1
        assert result.json()["items"][0]["source_name"] == "Düzenlenen"
        assert (await client.get("/api/rasathane/articles?limit=201")).status_code == 422
        assert (await client.get("/api/rasathane/articles?offset=-1")).status_code == 422
        assert (await client.get("/api/rasathane/articles?days=bad")).status_code == 422
        listed = (await client.get("/api/rasathane/sources")).json()["items"]
        current = next(row for row in listed if row["id"] == source["id"])
        assert current["article_count"] == 1 and current["supported"] is True


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
            await client.post("/api/rasathane/settings", json={"topic_refresh_minutes": 180})
        ).status_code == 422
        assert (
            await client.post(
                "/api/rasathane/research",
                content='{"query":"x"}',
                headers={"content-type": "text/plain"},
            )
        ).status_code == 400

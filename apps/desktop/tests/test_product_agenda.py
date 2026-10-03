from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from rasathane.product import agenda, api
from rasathane.product.service import JobCancelled, ProductService
from rasathane.product.store import ProductStore, now
from ytmcp.server import gui_http_app


@pytest.fixture
def store(tmp_path):
    store = ProductStore(tmp_path)
    feed = store.upsert_feed("Hukuk kaynağı", "https://example.org/feed", category="turk_hukuku")
    store.mark_feed(feed["id"])
    store.add_articles(
        feed["id"],
        [
            {
                "id": "law",
                "url": "https://example.org/law",
                "title": "KVKK araştırması",
                "summary": (
                    "Kişisel veri işleme yöntemleri incelendi. Açık kaynak araçlar karşılaştırıldı."
                ),
                "published_at": now(),
            },
            {
                "id": "old",
                "url": "https://example.org/old",
                "title": "Eski karar",
                "summary": "Eski karar bugün içeri aktarıldı.",
                "published_at": "2000-01-01",
            },
        ],
    )
    store.save_agenda_profile({"interests": "KVKK açık kaynak", "use_local_model": False})
    return store


def test_profile_context_snapshot_novelty_and_stale_articles(store):
    workspace = store.create_workspace("Hukuk ürünü")
    store.save_note(workspace["id"], "Veri işleme", "Açık kaynak araçların değerlendirilmesi")
    store.save_agenda_profile({"workspace_ids": [workspace["id"]]})
    service = ProductService(store, autostart=False)
    job = service.submit("agenda", {})
    assert service.run_once()
    result = store.get_job(job["id"])["result"]
    assert result["status"] == "updated"
    bulletin = store.get_bulletin(result["bulletin_id"])
    assert [i["article_id"] for i in bulletin["items"]] == ["law"]
    assert bulletin["method"] == "keyword_match"
    assert "model değerlendirmesi yok" in bulletin["notice"]
    assert "kvkk" in bulletin["items"][0]["matched_terms"]
    service.submit("agenda", {})
    service.run_once()
    assert len(store.list_bulletins()) == 1
    assert store.agenda_state()["status"] == "unchanged"
    store.save_agenda_profile({"project_context": "Yeni proje bağlamı"})
    service.submit("agenda", {})
    service.run_once()
    assert len(store.list_bulletins()) == 2
    assert ProductStore(store.directory).agenda_profile()["project_context"] == "Yeni proje bağlamı"


def test_grounded_local_model_evaluation_and_invented_evidence_rejected(store):
    store.save_agenda_profile({"use_local_model": True})

    def evaluate(payload, check):
        check()
        return [
            {
                "id": "law",
                "importance": "high",
                "relevance_reason": "KVKK ilgi alanıyla ilgili.",
                "project_impact": "Veri işleme tasarımını incelemek için başlangıç kaynağı.",
                "suggested_action": "Karşılaştırmanın tam metnini inceleyin.",
                "evidence_quote": "Kişisel veri işleme yöntemleri incelendi.",
            }
        ]

    result = agenda.build_agenda(store, lambda: None, evaluate)
    assert result["snapshot"]["method"] == "local_model"
    assert result["snapshot"]["items"][0]["evaluation_method"] == "local_model"

    def invented(payload, check):
        result = evaluate(payload, check)
        result[0]["evidence_quote"] = "Kaynakta bulunmayan uydurma yürürlük tarihi"
        return result

    result = agenda.build_agenda(store, lambda: None, invented)
    assert result["snapshot"]["method"] == "keyword_match"
    assert "doğrulanamadı" in result["model_error"]
    assert store.list_bulletins() == []  # Build alone never publishes.


def test_cancel_and_context_edit_cannot_publish(store):
    store.save_agenda_profile({"use_local_model": True})

    def cancel(payload, check):
        raise JobCancelled("İptal")

    with pytest.raises(JobCancelled):
        agenda.build_agenda(store, lambda: (_ for _ in ()).throw(JobCancelled()), cancel)
    result = agenda.build_agenda(store, lambda: None, lambda *_: [])
    job = store.enqueue_agenda({})
    store.save_agenda_profile({"project_context": "Değişti"})
    with pytest.raises(ValueError, match="bağlamı değişti"):
        store.finish_agenda(job["id"], result)
    assert store.list_bulletins() == []
    store.cancel(job["id"])
    with pytest.raises(ValueError, match="iptal"):
        store.finish_agenda(job["id"], result)


def test_queue_priority_dependencies_deduplication_and_native_account(store, monkeypatch):
    service = ProductService(store, autostart=False)
    for i in range(20):
        service.submit("feed_refresh", {"automatic": True, "source_id": str(i)})
    agenda_job = service.submit("agenda", {"automatic": True})
    assert service.submit("agenda", {})["id"] == agenda_job["id"]
    interactive = service.submit("research", {"query": "KVKK", "web": False})
    assert store.claim_next()["id"] == interactive["id"]
    store.update_job(interactive["id"], "completed")
    assert store.claim_next()["kind"] == "feed_refresh"
    for feed_job in store.list_jobs():
        if feed_job["kind"] == "feed_refresh":
            store.update_job(feed_job["id"], "completed")
    assert store.claim_next()["id"] == agenda_job["id"]
    store.update_job(agenda_job["id"], "completed")
    monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "test")
    before = len(store.list_jobs())
    service._schedule()
    assert len(store.list_jobs()) == before
    assert service.run_once() is False
    service.set_native_authenticated(False)
    assert all(j["status"] != "queued" for j in store.list_jobs())


def test_sources_refresh_waits_before_agenda_and_disabled_profile_does_not_schedule(
    store, monkeypatch
):
    service = ProductService(store, autostart=False)
    monkeypatch.setattr("rasathane.product.service.fetch_feed", lambda _: [])
    job = service.submit("agenda", {"refresh_sources": True})
    assert job["request"]["depends_on"]
    service.run_once()
    assert store.get_job(job["id"])["status"] == "queued"
    service.run_once()
    assert store.get_job(job["id"])["status"] == "completed"
    store.save_agenda_profile({"enabled": False})
    before = len(store.list_jobs())
    service._schedule_agenda()
    assert len(store.list_jobs()) == before


def test_auto_backoff_no_duplicate_and_empty_notice(store):
    service = ProductService(store, autostart=False)
    service._schedule_agenda()
    service._schedule_agenda()
    assert len(store.list_jobs()) == 1
    service.run_once()
    service._schedule_agenda()
    assert len(store.list_jobs()) == 1
    with store.connection() as conn:
        conn.execute(
            "UPDATE jobs SET created_at=?", ((datetime.now(UTC) - timedelta(hours=2)).isoformat(),)
        )
        conn.execute("UPDATE articles SET published_at='2000-01-01'")
    service._schedule_agenda()
    service.run_once()
    assert service.agenda_status()["latest"] is None
    assert store.agenda_state()["status"] == "empty"
    assert len(store.list_bulletins()) == 1  # Historical receipt remains accessible.


async def test_agenda_api_profile_validation_and_job_result(store, monkeypatch):
    service = ProductService(store, autostart=False)
    monkeypatch.setattr(api, "_service", service)
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        profile = (await client.get("/api/rasathane/agenda-profile")).json()
        assert profile["interests"] == "KVKK açık kaynak"
        invalid = await client.post("/api/rasathane/agenda-profile", json={"refresh_minutes": 1})
        assert invalid.status_code == 422
        unknown = await client.post(
            "/api/rasathane/agenda-profile", json={"workspace_ids": ["missing"]}
        )
        assert unknown.status_code == 400
        job = (await client.post("/api/rasathane/agenda", json={})).json()
        service.run_once()
        result = (await client.get("/api/rasathane/agenda")).json()
        assert result["latest"]["items"][0]["article_id"] == "law"
        assert result["status"]["job"]["id"] == job["id"]
        assert result["status"]["source_count"] == 1


def test_model_failure_retries_without_duplicate_history_and_cancel_during_model(
    store, monkeypatch
):
    store.save_agenda_profile({"use_local_model": True})
    monkeypatch.setattr(agenda, "local_evaluate", lambda *_: [])
    service = ProductService(store, autostart=False)
    for _ in range(2):
        service.submit("agenda", {})
        service.run_once()
    assert len(store.list_bulletins()) == 1
    assert store.agenda_state()["model_error"]
    job = service.submit("agenda", {})

    def cancel_inside(payload, check):
        store.cancel(job["id"])
        check()
        raise AssertionError("cancel check must raise")

    monkeypatch.setattr(agenda, "local_evaluate", cancel_inside)
    service.run_once()
    assert store.get_job(job["id"])["status"] == "cancelled"
    assert len(store.list_bulletins()) == 1


def test_local_generation_lease_starts_installed_model_with_bounded_cancel_hook(monkeypatch):
    from ytcore.local import llamacpp

    calls = []

    def start(kind, *, check, startup_timeout):
        check()
        calls.append((kind, startup_timeout))
        return "http://127.0.0.1:8077"

    monkeypatch.setattr(llamacpp, "sunucu_baslat_gerekirse", start)
    with llamacpp.generation_session(lambda: None) as host:
        assert host == "http://127.0.0.1:8077"
    assert calls == [("llm", 90)]
    with pytest.raises(JobCancelled):
        with llamacpp.generation_session(lambda: (_ for _ in ()).throw(JobCancelled())):
            raise AssertionError("cancelled session must not yield")


def test_official_metadata_is_not_treated_as_full_decision(store):
    with store.connection() as conn:
        conn.execute(
            "UPDATE articles SET provenance=? WHERE id='law'",
            ('{"text_scope":"official_metadata"}',),
        )
    result = agenda.build_agenda(store, lambda: None)
    item = result["snapshot"]["items"][0]
    assert item["status"] == "unavailable"
    assert item["summary"] == ""
    assert item["evidence_quote"] == item["title"]
    assert "tam metin okunmadı" in result["snapshot"]["notice"]


def test_concurrent_manual_agenda_refresh_is_one_atomic_source_batch(store):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    other = store.upsert_feed("AI", "https://example.org/ai.xml")
    barrier = Barrier(8)
    service = ProductService(store, autostart=False)

    def request(_):
        barrier.wait(timeout=10)
        return service.submit("agenda", {"refresh_sources": True})

    with ThreadPoolExecutor(max_workers=8) as pool:
        jobs = list(pool.map(request, range(8)))
    assert len({j["id"] for j in jobs}) == 1
    sources = [j for j in store.list_jobs() if j["kind"] == "feed_refresh"]
    assert len(sources) == 2
    assert other["id"] in {j["request"]["source_id"] for j in sources}
    job = store.get_job(jobs[0]["id"])
    assert set(job["request"]["depends_on"]) == {j["id"] for j in sources}


def test_new_source_batch_cannot_be_overtaken_by_queued_auto_agenda(store):
    service = ProductService(store, autostart=False)
    job = service.submit("agenda", {"automatic": True})
    source_job = service.submit("feed_refresh", {"automatic": True, "source_id": "late"})
    assert store.claim_next()["id"] == source_job["id"]
    store.update_job(source_job["id"], "failed", error="Fixture ağ hatası")
    assert store.claim_next()["id"] == job["id"]


def test_worker_schedules_due_sources_before_claiming_old_agenda(store, monkeypatch):
    service = ProductService(store, autostart=False)
    job = service.submit("agenda", {"automatic": True})
    with store.connection() as conn:
        conn.execute("UPDATE feeds SET last_refreshed_at=NULL")
    monkeypatch.setattr("rasathane.product.service.fetch_feed", lambda _: [])
    run_once = service.run_once

    def run_and_stop():
        result = run_once()
        service._stop.set()
        return result

    monkeypatch.setattr(service, "run_once", run_and_stop)
    service._loop()
    assert store.get_job(job["id"])["status"] == "queued"
    source_jobs = [j for j in store.list_jobs() if j["kind"] == "feed_refresh"]
    assert len(source_jobs) == 1
    assert source_jobs[0]["status"] == "completed"


def test_window_scan_preserves_older_relevant_source_and_source_diversity(store):
    busy = store.upsert_feed("Sık teknoloji akışı", "https://example.org/busy.xml")
    store.add_articles(
        busy["id"],
        [
            {
                "id": f"busy{i}",
                "url": f"https://example.org/busy/{i}",
                "title": "Yeni telefon ekranı",
                "summary": "Ekran boyutu ve pil kapasitesi.",
                "published_at": now(),
            }
            for i in range(600)
        ],
    )
    with store.connection() as conn:
        conn.execute(
            "UPDATE articles SET published_at=? WHERE id='law'",
            ((datetime.now(UTC) - timedelta(hours=2)).isoformat(),),
        )
    selected = agenda.candidates(store, store.agenda_profile())
    assert len(selected) == 200
    assert selected[0]["id"] == "law"
    assert "old" not in {a["id"] for a in selected}
    store.add_articles(
        busy["id"],
        [
            {
                "id": f"relevant{i}",
                "url": f"https://example.org/relevant/{i}",
                "title": "KVKK açık kaynak",
                "summary": "KVKK açık kaynak karşılaştırması.",
                "published_at": now(),
            }
            for i in range(12)
        ],
    )
    bulletin = agenda.build_agenda(store, lambda: None)["snapshot"]
    assert "law" in {i["article_id"] for i in bulletin["items"]}
    assert len(bulletin["items"]) == 8
    with pytest.raises(JobCancelled):
        agenda.candidates(
            store, store.agenda_profile(), check=lambda: (_ for _ in ()).throw(JobCancelled())
        )


def test_generation_profile_is_scoped_to_lease_and_restored(monkeypatch):
    from types import SimpleNamespace

    from ytcore.local import llamacpp

    monkeypatch.setattr(llamacpp, "get_config", lambda: SimpleNamespace(llamacpp_profil="ram16"))
    observed = []

    def start(*_, **__):
        observed.append(llamacpp.aktif_profil())
        return "http://127.0.0.1:8077"

    monkeypatch.setattr(llamacpp, "sunucu_baslat_gerekirse", start)
    with llamacpp.generation_session(lambda: None, profile="ram8"):
        assert llamacpp.aktif_profil() == "ram8"
    assert observed == ["ram8"]
    assert llamacpp.aktif_profil() == "ram16"


def test_status_reports_source_batch_progress_and_hides_stale_context(store, monkeypatch):
    service = ProductService(store, autostart=False)
    monkeypatch.setattr("rasathane.product.service.fetch_feed", lambda _: [])
    job = service.submit("agenda", {"refresh_sources": True})
    pending = service.agenda_status()
    assert pending["latest"] is None
    assert pending["status"]["source_batch"] == {
        "total": 1,
        "active": 1,
        "completed": 0,
        "failed": 0,
    }
    service.run_once()
    fetched = service.agenda_status()
    assert fetched["status"]["source_batch"]["completed"] == 1
    assert fetched["status"]["source_batch"]["active"] == 0
    service.run_once()
    assert store.get_job(job["id"])["status"] == "completed"
    assert service.agenda_status()["latest"] is not None
    store.save_agenda_profile({"project_context": "Yeni ilgi bağlamı"})
    stale = service.agenda_status()
    assert stale["latest"] is None
    assert stale["status"]["latest_is_stale"] is True
    assert "bağlamı değişti" in stale["status"]["notice"]
    assert len(store.list_bulletins()) == 1

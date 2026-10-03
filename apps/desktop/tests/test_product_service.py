from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore
from rasathane.product.web import validate_public_url


class Search:
    name = "test"

    def search(self, query, limit=5):
        return [{"title": "İş hukuku", "url": "https://example.com/law", "excerpt": "İşçilik"}]


def test_real_sqlite_research_persists_citations_and_source_version(tmp_path):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Araştırma")
    store.save_note(workspace["id"], "İşçilik", "İşçilik alacağı")
    service = ProductService(
        store,
        search=Search(),
        fetch=lambda url: {"title": "Kanun", "body": "İşçilik alacağı kanun metni", "url": url},
        autostart=False,
    )
    job = service.submit("research", {"query": "iscilik", "web": True})
    service.run_once()
    result = store.get_job(job["id"])["result"]
    assert result["local_results"]
    assert result["web_results"][0]["content_hash"]
    assert result["web_results"][0]["version_id"]
    assert store.search("kanun")
    assert store.export()["notes"]


def test_retired_jobs_and_context_are_rejected_before_queue(tmp_path):
    store = ProductStore(tmp_path)
    service = ProductService(store, search=Search(), autostart=False)
    with pytest.raises(ValueError, match="iş türü"):
        service.submit("refresh", {"topic_id": "old"})
    for key in ("workspace_id", "topic_id"):
        with pytest.raises(ValueError, match="artık desteklenmiyor"):
            service.submit("research", {"query": "q", key: "old"})
    assert store.list_jobs() == []


def test_cancel_running_research_does_not_report_completion(tmp_path):
    store = ProductStore(tmp_path)
    started, proceed = threading.Event(), threading.Event()

    def fetch(url):
        started.set()
        proceed.wait(5)
        return {"title": "X", "body": "X", "url": url}

    service = ProductService(store, search=Search(), fetch=fetch, autostart=False)
    job = service.submit("research", {"query": "q", "web": True})
    worker = threading.Thread(target=service.run_once)
    worker.start()
    assert started.wait(5)
    assert store.cancel(job["id"])["status"] == "cancel_requested"
    proceed.set()
    worker.join(5)
    assert store.get_job(job["id"])["status"] == "cancelled"


def test_analysis_keeps_full_engine_result(tmp_path):
    store = ProductStore(tmp_path)

    def engine(request, cancelled, progress):
        return {
            "ozet_detay": "Gerçek engine kontratı",
            "factcheck_iddialar": [],
            "motor": {"backend": "llamacpp"},
            "cloud_cagrisi_sayisi": 0,
            "stub": False,
        }

    service = ProductService(store, analysis=engine, autostart=False)
    job = service.submit(
        "analysis", {"url": "https://example.com", "konu": "hukuk", "asr_izin": False}
    )
    service.run_once()
    result = store.get_job(job["id"])["result"]
    assert result["ozet_detay"] == "Gerçek engine kontratı"
    assert result["cloud_cagrisi_sayisi"] == 0
    assert result["motor"]["backend"] == "llamacpp"


def test_acquisition_error_remains_failed_job_and_preserves_error_receipt(tmp_path):
    store = ProductStore(tmp_path)
    receipt = {
        "transkript_durumu": "hata",
        "kaynak_durumu": "kodlama_hatasi",
        "transkript_hata": "Kaynak metni karakter kodlamasıyla okunamadı.",
        "ozet_detay": "",
        "quality_provenance": {"source": {"acquisition_status": "kodlama_hatasi"}},
        "artifacts": [],
    }
    service = ProductService(
        store, analysis=lambda request, cancelled, progress: receipt, autostart=False
    )
    job = service.submit("analysis", {"url": "https://example.com/broken"})
    assert service.run_once()
    saved = store.get_job(job["id"])
    assert saved["status"] == "failed"
    assert saved["error"] == receipt["transkript_hata"]
    assert saved["result"] == receipt
    assert store.library() == []


def test_default_provider_pii_gate_allows_clean_query_and_blocks_person(tmp_path, monkeypatch):
    import rasathane.product.service as module

    calls = []

    class Provider(Search):
        def search(self, query, limit=5):
            calls.append(query)
            return super().search(query, limit)

    monkeypatch.setattr(module, "search_provider", lambda choice: Provider())
    store = ProductStore(tmp_path)
    service = ProductService(store, fetch=lambda url: {"body": "Resmî araştırma"}, autostart=False)
    clean = service.submit("research", {"query": "resmi gazete", "web": True})
    service.run_once()
    assert store.get_job(clean["id"])["result"]["web_results"]
    assert calls == ["resmi gazete"]
    person = service.submit("research", {"query": "Ahmet Yılmaz dava", "web": True})
    service.run_once()
    assert store.get_job(person["id"])["result"]["status"] == "web_blocked_pii"
    assert calls == ["resmi gazete"]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://user:pw@example.com/",
        "http://localhost/",
        "http://[::1]/",
    ],
)
def test_ssrf_rejected_before_provider(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_unconfigured_search_failure_is_visible_and_not_empty_success(tmp_path):
    class Broken:
        name = "broken"

        def search(self, query, limit=5):
            raise RuntimeError("Arama sağlayıcısı yanıt vermedi")

    store = ProductStore(tmp_path)
    service = ProductService(store, search=Broken(), autostart=False)
    job = service.submit("research", {"query": "q", "web": True})
    service.run_once()
    assert store.get_job(job["id"])["status"] == "failed"
    assert store.get_job(job["id"])["error"]


def test_scheduler_ignores_legacy_topics_but_still_refreshes_sources(tmp_path):
    store = ProductStore(tmp_path)
    topic = store.create_topic("Eski", "eski")
    yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    with store.connection() as conn:
        conn.execute("UPDATE topics SET last_refreshed_at=? WHERE id=?", (yesterday, topic["id"]))
        conn.execute("INSERT INTO settings VALUES('topic_refresh_minutes','15')")
    service = ProductService(store, search=Search(), autostart=False)
    source = store.upsert_feed("Kaynak", "https://example.org/feed")
    service._schedule()
    assert [job["kind"] for job in store.list_jobs()] == ["feed_refresh"]
    assert store.list_jobs()[0]["request"]["source_id"] == source["id"]
    assert store.list_topics()[0]["last_refreshed_at"] == yesterday
    assert "topic_refresh_minutes" not in store.settings()
    with pytest.raises(ValueError, match="Desteklenmeyen ayar"):
        store.save_settings({"topic_refresh_minutes": 0})


def test_upgrade_cancels_legacy_topic_jobs_without_deleting_history(tmp_path):
    store = ProductStore(tmp_path)
    topic = store.create_topic("Kararlar", "kararlar")
    completed = store.enqueue("analysis", {})
    pending = store.enqueue("analysis", {})
    store.update_job(completed["id"], "completed", result={"new_count": 2})
    with store.connection() as conn:
        conn.execute(
            "UPDATE jobs SET kind='refresh',request=?", ('{"topic_id":"' + topic["id"] + '"}',)
        )
    reopened = ProductStore(tmp_path)
    assert reopened.get_job(completed["id"])["result"] == {"new_count": 2}
    retired = reopened.get_job(pending["id"])
    assert retired["status"] == "cancelled" and retired["cancel_requested"]
    assert "kaldırıldığı" in retired["error"]
    assert reopened.list_topics() == [topic]
    assert reopened.list_jobs() == []
    assert len(reopened.export()["jobs"]) == 2
    service = ProductService(reopened, search=Search(), autostart=False)
    assert not service.run_once()


def test_default_public_feed_config_has_zero_fixture_articles_and_keeps_disabled_feed(tmp_path):
    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    service.ensure_official_feeds()
    assert store.counts()["sources"] == 2 and store.counts()["articles"] == 0
    legal = next(feed for feed in store.list_feeds() if feed["kind"] == "yargitay_public")
    store.upsert_feed(legal["name"], legal["url"], legal["kind"], enabled=False)
    service.ensure_official_feeds()
    assert store.counts()["sources"] == 2
    assert not next(feed for feed in store.list_feeds() if feed["id"] == legal["id"])["enabled"]


def test_public_feed_cache_and_retry_after_prevent_repeated_network(tmp_path, monkeypatch):
    import rasathane.product.service as module
    from rasathane.product.web import SourceRateLimited

    store = ProductStore(tmp_path)
    feed = store.upsert_feed("Public Yargıtay", "https://mevzuat.adalet.gov.tr/", "yargitay_public")
    calls = []

    def fetch(feed):
        calls.append(feed["id"])
        return [{"title": "Karar", "url": "https://mevzuat.adalet.gov.tr/ictihat/1"}]

    monkeypatch.setattr(module, "fetch_feed", fetch)
    service = ProductService(store, autostart=False)
    first = service.submit("feed_refresh", {"source_id": feed["id"]})
    service.run_once()
    assert store.get_job(first["id"])["result"]["inserted"] == 1
    second = service.submit("feed_refresh", {"source_id": feed["id"]})
    service.run_once()
    assert store.get_job(second["id"])["result"]["sources"][0]["cached"]
    assert len(calls) == 1
    with store.connection() as conn:
        conn.execute(
            "UPDATE feeds SET last_refreshed_at=NULL,metadata='{}' WHERE id=?", (feed["id"],)
        )
    monkeypatch.setattr(
        module, "fetch_feed", lambda feed: (_ for _ in ()).throw(SourceRateLimited("720"))
    )
    failure = service.submit("feed_refresh", {"source_id": feed["id"]})
    service.run_once()
    assert store.get_job(failure["id"])["status"] == "failed"
    current = store.list_feeds()[0]
    assert current["last_refreshed_at"] is None
    delay = (
        datetime.fromisoformat(current["metadata"]["next_attempt_at"])
        - datetime.fromisoformat(current["metadata"]["last_attempt_at"])
    ).total_seconds()
    assert delay == 720
    service._schedule()
    assert len(store.list_jobs()) == 3

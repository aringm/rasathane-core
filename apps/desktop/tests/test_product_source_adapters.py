from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from rasathane.product import connectors
from rasathane.product.service import ProductService
from rasathane.product.store import ProductStore

ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>Research update</title><link rel="self" href="https://example.org/internal"/>
<link rel="alternate" href="https://example.org/article"/>
<summary>Publisher abstract</summary><published>2026-10-03T12:00:00Z</published>
</entry></feed>"""


@pytest.mark.parametrize(
    "kind,url,expected",
    [
        (
            "arxiv",
            "http://export.arxiv.org/api/query?search_query=cat:cs.AI",
            "https://export.arxiv.org/api/query?search_query=cat:cs.AI",
        ),
        (
            "reddit",
            "https://www.reddit.com/r/LocalLLaMA/top.json?t=day&limit=15",
            "https://www.reddit.com/r/LocalLLaMA/top.rss?t=day&limit=15",
        ),
        ("reddit", "https://www.reddit.com/r/law", "https://www.reddit.com/r/law/new.rss"),
        (
            "youtube_channel",
            "https://www.youtube.com/channel/UC" + "a" * 22 + "/videos",
            "https://www.youtube.com/feeds/videos.xml?channel_id=UC" + "a" * 22,
        ),
    ],
)
def test_legacy_sources_use_safe_rss_and_preserve_configured_url(monkeypatch, kind, url, expected):
    calls = []
    monkeypatch.setattr(connectors, "safe_get", lambda target: calls.append(target) or ATOM)
    monkeypatch.setattr(connectors, "_arxiv_last_request", 0)
    result = connectors.fetch_feed({"kind": kind, "url": url, "metadata": {}})
    assert calls == [expected]
    assert result[0]["url"] == "https://example.org/article"
    assert result[0]["summary"] == "Publisher abstract"
    assert result[0]["provenance"]["connector"] == kind
    assert result[0]["provenance"]["configured_url"] == url


def test_youtube_handle_uses_page_external_id_not_recommended_video(monkeypatch):
    calls = []
    channel = "UC" + "x" * 22

    def get(url):
        calls.append(url)
        if "/feeds/" in url:
            return ATOM
        return ('{"channelId":"UC' + "y" * 22 + '","externalId":"' + channel + '"}').encode()

    monkeypatch.setattr(connectors, "safe_get", get)
    rows = connectors.fetch_feed(
        {"kind": "youtube_channel", "url": "https://www.youtube.com/@example/videos"}
    )
    assert rows and calls[-1].endswith("channel_id=" + channel)
    monkeypatch.setattr(
        connectors, "safe_get", lambda url: b'{"channelId":"UCyyyyyyyyyyyyyyyyyyyyyy"}'
    )
    with pytest.raises(ValueError, match="kimliği bulunamadı"):
        connectors.fetch_feed(
            {"kind": "youtube_channel", "url": "https://www.youtube.com/@example/videos"}
        )


@pytest.mark.parametrize(
    "kind,url",
    [
        ("arxiv", "http://127.0.0.1/private"),
        ("arxiv", "https://evil.example/api/query"),
        ("reddit", "https://www.reddit.com.evil.example/r/law"),
        ("reddit", "https://www.reddit.com/user/example"),
        ("youtube_channel", "https://www.youtube.com/watch?v=abc"),
        ("youtube_channel", "https://www.youtube.com/feeds/videos.xml?channel_id=http://127.0.0.1"),
    ],
)
def test_legacy_adapter_rejects_wrong_hosts_and_input_without_fetch(monkeypatch, kind, url):
    calls = []
    monkeypatch.setattr(connectors, "safe_get", lambda url: calls.append(url) or ATOM)
    with pytest.raises(ValueError):
        connectors.fetch_feed({"kind": kind, "url": url})
    assert calls == []


def test_source_scheduler_independent_from_topic_search_and_respects_source_controls(tmp_path):
    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    enabled = store.upsert_feed(
        "RSS", "https://example.org/rss", metadata={"fetch_interval_minutes": 60}
    )
    paused = store.upsert_feed("Kapalı", "https://example.org/off", enabled=False)
    unsupported = store.upsert_feed("Eski", "https://example.org/legacy", kind="unknown")
    recent = store.upsert_feed("Yeni", "https://example.org/new")
    backed_off = store.upsert_feed("Bekle", "https://example.org/later")
    store.mark_feed(recent["id"])
    store.record_feed_attempt(backed_off["id"], 600)
    store.save_settings({"web_enabled": False})
    service._schedule()
    service._schedule()
    jobs = store.list_jobs()
    assert len(jobs) == 1 and jobs[0]["request"]["source_id"] == enabled["id"]
    assert not any(j["request"]["source_id"] in {paused["id"], unsupported["id"]} for j in jobs)


def test_rss_failure_has_retry_backoff_and_success_clears_it(tmp_path, monkeypatch):
    import rasathane.product.service as module

    store = ProductStore(tmp_path)
    feed = store.upsert_feed("RSS", "https://example.org/rss")
    service = ProductService(store, autostart=False)
    monkeypatch.setattr(
        module, "fetch_feed", lambda feed: (_ for _ in ()).throw(ValueError("HTTP 503"))
    )
    job = service.submit("feed_refresh", {"source_id": feed["id"]})
    service.run_once()
    assert store.get_job(job["id"])["status"] == "failed"
    assert store.list_feeds()[0]["metadata"]["next_attempt_at"]
    service._schedule()
    assert len(store.list_jobs()) == 1
    with store.connection() as conn:
        conn.execute(
            "UPDATE feeds SET metadata=json_set(metadata,'$.next_attempt_at',?)",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),),
        )
    monkeypatch.setattr(module, "fetch_feed", lambda feed: [])
    service.submit("feed_refresh", {"source_id": feed["id"]})
    service.run_once()
    assert "next_attempt_at" not in store.list_feeds()[0]["metadata"]
    service._schedule()
    assert len(store.list_jobs()) == 2


def test_interactive_work_precedes_twenty_automatic_source_jobs(tmp_path):
    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    for i in range(20):
        store.upsert_feed(f"Kaynak {i}", f"https://example.org/feed/{i}")
    service._schedule()
    assert len(store.list_jobs()) == 20
    assert all(job["request"]["automatic"] for job in store.list_jobs())
    research = service.submit("research", {"query": "araştırma", "web": False})
    assert store.claim_next()["id"] == research["id"]
    store.update_job(research["id"], "completed")
    manual = service.submit("feed_refresh", {"source_id": store.list_feeds()[0]["id"]})
    assert store.claim_next()["id"] == manual["id"]


def test_source_scheduler_deduplicates_beyond_recent_history_window(tmp_path):
    store = ProductStore(tmp_path)
    service = ProductService(store, autostart=False)
    store.upsert_feed("Kaynak", "https://example.org/feed")
    service._schedule()
    for _ in range(101):
        job = store.enqueue("analysis", {"url": "https://example.org/article"})
        store.update_job(job["id"], "completed")
    service._schedule()
    assert len(store.list_jobs(limit=200)) == 102


@pytest.mark.parametrize("change", ["url", "kind", "pause", "pause_resume"])
@pytest.mark.parametrize("failed", [False, True])
def test_source_edit_during_fetch_discards_old_response_and_status(
    tmp_path, monkeypatch, change, failed
):
    import rasathane.product.service as module

    store = ProductStore(tmp_path)
    source = store.upsert_feed("Kaynak", "https://example.org/old")
    service = ProductService(store, autostart=False)
    after_edit = []

    def fetch(feed):
        if change == "url":
            store.update_feed(source["id"], url="https://example.org/new")
        elif change == "kind":
            store.update_feed(source["id"], kind="reddit")
        else:
            store.update_feed(source["id"], enabled=False)
            if change == "pause_resume":
                store.update_feed(source["id"], enabled=True)
        after_edit.append(store.get_feed(source["id"]))
        if failed:
            raise ValueError("Eski adres yanıt vermedi")
        return [{"title": "Eski yanıt", "url": "https://example.org/article"}]

    monkeypatch.setattr(module, "fetch_feed", fetch)
    job = service.submit("feed_refresh", {"source_id": source["id"]})
    service.run_once()
    assert store.get_job(job["id"])["status"] == "completed"
    assert store.get_job(job["id"])["result"]["sources"][0]["skipped"] == "configuration_changed"
    assert store.list_articles() == []
    assert store.get_feed(source["id"]) == after_edit[0]


def test_source_paused_while_queued_is_not_fetched(tmp_path, monkeypatch):
    import rasathane.product.service as module

    store = ProductStore(tmp_path)
    source = store.upsert_feed("Kaynak", "https://example.org/feed")
    service = ProductService(store, autostart=False)
    job = service.submit("feed_refresh", {"source_id": source["id"]})
    store.update_feed(source["id"], enabled=False)
    monkeypatch.setattr(module, "fetch_feed", lambda feed: pytest.fail("Paused source fetched"))
    service.run_once()
    assert store.get_job(job["id"])["result"]["sources"][0]["skipped"] == "paused_or_removed"
    assert store.get_feed(source["id"])["last_refreshed_at"] is None

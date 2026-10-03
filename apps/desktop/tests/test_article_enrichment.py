from __future__ import annotations

import httpx
import pytest
from rasathane.product import api, article_enrichment, bulletins, connectors, news
from rasathane.product.service import JobCancelled, ProductService
from rasathane.product.store import ProductStore, now
from ytmcp.server import gui_http_app

HN = """<rss><channel><item><title>Local models process documents on device</title>
<link>https://news.ycombinator.com/item?id=123</link><description><![CDATA[
<p>Article URL: <a href="https://example.org/article">https://example.org/article</a></p>
<p>Comments URL: <a href="https://news.ycombinator.com/item?id=123">https://news.ycombinator.com/item?id=123</a></p>
<p>Points: 200</p><p># Comments: 40</p>]]></description></item></channel></rss>"""
BODY = (
    "Local models process documents on the device. The experiment measured memory use "
    "with eight gigabytes of RAM. No files were sent to a remote service during the experiment."
)
TR = (
    "Yerel modeller belgeleri cihazda işliyor. Denemede sekiz GB RAM ile bellek kullanımı "
    "ölçüldü. Kaynakta dosyaların uzak servise gönderilmediği belirtiliyor."
)


@pytest.fixture
def store(tmp_path):
    store = ProductStore(tmp_path)
    feed = store.upsert_feed("Hacker News", "https://hnrss.org/frontpage")
    store.add_articles(
        feed["id"],
        [
            {
                "id": "hn",
                "title": "Local models process documents on device",
                "url": "https://news.ycombinator.com/item?id=123",
                "summary": "Article URL: https://example.org/article "
                "Comments URL: https://news.ycombinator.com/item?id=123 Points: 200 # Comments: 40",
                "published_at": now(),
            }
        ],
    )
    return store


def evaluation(payload, check):
    check()
    assert "Points:" not in payload["text"]
    return {
        "title": "Yerel modeller belgeleri cihazda işliyor",
        "summary": TR,
        "evidence_quote": "Local models process documents on the device.",
    }


def test_hn_connector_uses_article_url_and_does_not_save_points_as_news(monkeypatch):
    monkeypatch.setattr(connectors, "safe_get", lambda _: HN.encode())
    row = connectors.fetch_rss("https://hnrss.org/frontpage")[0]
    assert row["url"] == "https://example.org/article"
    assert row["summary"] == ""
    assert row["provenance"]["text_scope"] == "link_metadata"
    assert row["provenance"]["comments_url"].startswith("https://news.ycombinator.com/")
    unsafe = HN.replace("https://example.org/article", "http://127.0.0.1/secret")
    monkeypatch.setattr(connectors, "safe_get", lambda _: unsafe.encode())
    assert connectors.fetch_rss("https://hnrss.org/frontpage") == []


def test_old_hn_archive_is_pending_then_cached_turkish_from_real_article(store):
    pending = store.article_page()["items"][0]
    assert pending["url"] == "https://example.org/article"
    assert pending["summary_display"]["summary"] == ""
    assert pending["summary_display"]["status"] == "not_prepared"
    fetched = []

    def fetch(url):
        fetched.append(url)
        return {"url": url, "body": BODY}

    result = article_enrichment.enrich_article(store, "hn", lambda: None, fetch, evaluation)
    assert fetched == ["https://example.org/article"]
    assert result["summary"] == TR and result["method"] == "local_model"
    readback = news.summarize_article(ProductStore(store.directory), "hn")
    assert readback == result
    assert store.article_page()["items"][0]["summary_display"]["summary"] == TR
    assert "Points: 200" in store.list_articles()[0]["summary"]  # archive preserved
    with store.connection() as conn:
        conn.execute("UPDATE articles SET summary='Changed English excerpt' WHERE id='hn'")
    assert news.summarize_article(store, "hn")["summary"] == ""  # input hash invalidation


@pytest.mark.parametrize(
    "response",
    [
        {"title": "English title", "summary": BODY, "evidence_quote": BODY[:70]},
        {
            "title": "Türkçe başlık",
            "summary": TR,
            "evidence_quote": "Invented source claim is accepted everywhere.",
        },
    ],
)
def test_no_fake_english_or_ungrounded_summary_is_cached(store, response):
    with pytest.raises(ValueError):
        article_enrichment.enrich_article(
            store, "hn", lambda: None, lambda url: {"url": url, "body": BODY}, lambda *_: response
        )
    assert store.rows("SELECT * FROM article_summaries") == []


def test_fetch_failure_and_cancel_remain_truthful_without_cache(store, monkeypatch):
    service = ProductService(
        store,
        autostart=False,
        fetch=lambda _: (_ for _ in ()).throw(ValueError("Kaynak sayfası okunamadı")),
    )
    pending = service.request_article_summary("hn")
    assert service.request_article_summary("hn")["job_id"] == pending["job_id"]
    service.run_once()
    assert store.get_job(pending["job_id"])["status"] == "failed"
    failed = news.summarize_article(store, "hn")
    assert failed["status"] == "failed" and failed["summary"] == ""
    retry = service.request_article_summary("hn")
    assert retry["job_id"] != pending["job_id"]
    service.store.cancel(retry["job_id"])
    with pytest.raises(JobCancelled):
        article_enrichment.enrich_article(
            store, "hn", lambda: (_ for _ in ()).throw(JobCancelled()), lambda _: {}, evaluation
        )
    assert store.rows("SELECT * FROM article_summaries") == []


def test_background_is_limited_not_full_archive_and_account_gated(store, monkeypatch):
    feed = store.list_feeds()[0]
    store.add_articles(
        feed["id"],
        [
            {
                "id": f"a{i}",
                "url": f"https://example.org/a{i}",
                "title": "Article",
                "summary": BODY,
                "published_at": now(),
            }
            for i in range(500)
        ],
    )
    service = ProductService(store, autostart=False)
    monkeypatch.setenv("RASATHANE_SESSION_TOKEN", "fixture")
    service._schedule()
    assert store.list_jobs() == []
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN")
    for _ in range(12):
        service._schedule_summaries()
    jobs = store.list_jobs()
    assert len(jobs) == 2
    assert all(j["kind"] == "article_summary" for j in jobs)
    for _ in range(10):
        for j in store.list_jobs():
            store.update_job(j["id"], "completed")
        service._schedule_summaries()
    assert len(store.list_jobs()) <= 8


async def test_summary_api_pending_worker_cached_readback_and_turkish_speech(store, monkeypatch):
    service = ProductService(store, autostart=False, fetch=lambda url: {"url": url, "body": BODY})
    monkeypatch.setattr(api, "_service", service)
    monkeypatch.setattr(article_enrichment, "translate_local", evaluation)
    monkeypatch.setattr(news, "speak_text", lambda text: b"RIFF" + text.encode())
    monkeypatch.delenv("RASATHANE_SESSION_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gui_http_app()), base_url="http://localhost"
    ) as client:
        path = "/api/rasathane/articles/hn/summary"
        pending = await client.post(path, json={})
        assert pending.status_code == 202 and pending.json()["status"] == "pending"
        job_id = pending.json()["job_id"]
        assert (await client.post(path, json={})).json()["job_id"] == job_id
        service.run_once()
        ready = await client.post(path, json={})
        assert ready.status_code == 200 and ready.json()["summary"] == TR
        assert (await client.get("/api/rasathane/articles")).json()["items"][0]["summary_display"][
            "summary"
        ] == TR
        speech = await client.post("/api/rasathane/articles/hn/speech", json={})
        assert speech.status_code == 200
        assert speech.content == b"RIFF" + TR.encode()
        assert len(store.list_jobs()) == 1


@pytest.mark.parametrize(
    "body",
    [
        "Verify you are human. Enable JavaScript to continue reading this website.",
        "Subscribe to continue reading. This article requires a paid subscription.",
        "Çerezleri kabul edin. Bu sayfaya devam etmek için çerez seçeneklerinizi yapılandırın.",
    ],
)
def test_challenge_paywall_cookie_page_is_not_news(store, body):
    calls = []
    with pytest.raises(ValueError, match="haber metni okunamadı"):
        article_enrichment.enrich_article(
            store,
            "hn",
            lambda: None,
            lambda url: {"url": url, "body": body},
            lambda *_: calls.append(True),
        )
    assert calls == []
    assert store.rows("SELECT * FROM article_summaries") == []
    assert not news.restricted_source(BODY * 20 + " Subscribe to continue reading.")


def test_cancel_during_model_does_not_publish_summary(store):
    def cancelled(*_):
        raise JobCancelled("İptal")

    with pytest.raises(JobCancelled):
        article_enrichment.enrich_article(
            store, "hn", lambda: None, lambda url: {"url": url, "body": BODY}, cancelled
        )
    assert store.rows("SELECT * FROM article_summaries") == []


def test_long_challenge_footer_is_rejected_before_model(store):
    calls = []
    with pytest.raises(ValueError, match="haber metni okunamadı"):
        article_enrichment.enrich_article(
            store,
            "hn",
            lambda: None,
            lambda url: {"url": url, "title": "Just a moment", "body": "Footer links " * 300},
            lambda *_: calls.append(True),
        )
    assert calls == [] and store.rows("SELECT * FROM article_summaries") == []


def test_paywall_can_use_real_publisher_excerpt_but_never_link_metadata(store):
    with store.connection() as conn:
        conn.execute(
            "UPDATE articles SET summary=?,url=? WHERE id='hn'",
            (BODY, "https://example.org/article"),
        )
    result = article_enrichment.enrich_article(
        store,
        "hn",
        lambda: None,
        lambda url: {"url": url, "body": "Subscribe to continue reading."},
        evaluation,
    )
    assert result["summary"] == TR and result["text_scope"] == "feed_excerpt"
    assert "yalnız yayıncının RSS/Atom" in result["notice"]
    assert result["evidence_quote"] in BODY


def test_model_bulletin_provenance_and_historical_projection_are_truthful(store, monkeypatch):
    legacy = {
        "id": "legacy",
        "title": "Eski bülten",
        "created_at": now(),
        "notice": "Eski notice",
        "items": [
            {
                "article_id": "hn",
                "title": "English title",
                "summary": BODY,
                "url": "https://news.ycombinator.com/item?id=123",
                "status": "ready",
                "method": "extractive",
                "notice": "Eski notice",
                "text_scope": "feed_excerpt",
            }
        ],
        "summary": BODY,
        "article_count": 1,
        "ready_count": 1,
        "method": "extractive",
    }
    from rasathane.product.store import digest, json_text

    legacy["content_hash"] = digest(json_text(legacy))
    store.save_bulletin(legacy)
    before = bulletins.present_bulletin(store, "legacy")
    assert before["items"][0]["summary"] == "" and BODY not in before["summary"]
    article_enrichment.enrich_article(
        store,
        "hn",
        lambda: None,
        lambda url: {"url": url, "body": BODY},
        evaluation,
    )
    projected = bulletins.present_bulletin(store, "legacy")
    assert projected["items"][0]["summary"] == TR
    assert projected["method"] == "local_model"
    assert projected["source_content_hash"] == legacy["content_hash"]
    assert store.get_bulletin("legacy") == legacy  # immutable archive, GET writes nothing
    new = bulletins.create_bulletin(store, ["hn"])
    assert new["method"] == "local_model" and "cümle seçilerek" not in new["notice"]
    assert "Modelle" in new["notice"]
    speech = []
    monkeypatch.setattr(bulletins, "speak_text", lambda text, **_: speech.append(text) or b"RIFF")
    bulletins.speak_bulletin(store, "legacy")
    assert TR in speech[0] and BODY not in speech[0]
    assert "cihazdaki modelle" in speech[0]
    from rasathane.product.agenda import _assessment_text

    assert _assessment_text(projected["items"][0]) == BODY


def test_projection_refreshes_empty_history_without_replacing_agenda_assessment_evidence(store):
    from rasathane.product.store import digest, json_text

    original_quote = "The experiment measured memory use with eight gigabytes of RAM."
    saved = {
        "id": "agenda-old",
        "title": "Gündem",
        "created_at": now(),
        "agenda": True,
        "items": [
            {
                "article_id": "hn",
                "title": "English title",
                "summary": "",
                "url": "https://example.org/article",
                "status": "not_prepared",
                "method": "pending",
                "notice": "Henüz hazırlanmadı",
                "text_scope": "feed_excerpt",
                "evidence_quote": original_quote,
                "source_hash": "assessment-source-hash",
                "relevance_reason": "Yerel bellek sınırı ilgi alanına uyuyor.",
                "project_impact": "Bellek profili değerlendirilebilir.",
                "suggested_action": "Deneme sonuçlarını inceleyin.",
            }
        ],
        "summary": "",
        "notice": "Önceki gündem",
        "article_count": 1,
        "ready_count": 0,
        "method": "keyword_match",
    }
    saved["content_hash"] = digest(json_text(saved))
    store.save_bulletin(saved)
    article_enrichment.enrich_article(
        store,
        "hn",
        lambda: None,
        lambda url: {"url": url, "body": BODY},
        evaluation,
    )
    projected = bulletins.present_bulletin(store, saved["id"])
    item = projected["items"][0]
    assert item["summary"] == TR and item["status"] == "ready"
    assert item["evidence_quote"] == original_quote
    assert item["source_hash"] == "assessment-source-hash"
    assert item["summary_evidence_quote"] == "Local models process documents on the device."
    assert item["relevance_reason"] == saved["items"][0]["relevance_reason"]
    assert projected["method"] == "keyword_match" and projected["summary_method"] == "local_model"
    assert store.get_bulletin(saved["id"]) == saved

from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest
from rasathane.product.migration import import_radar_snapshot, read_radar_postgres
from rasathane.product.store import ProductStore


def test_wal_workspace_note_and_turkish_fts(tmp_path):
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("İş hukuku")
    note = store.save_note(workspace["id"], "İşçi hakları", "İşçilik alacağı ve kıdem tazminatı")
    assert store.search("iscilik alacagi", workspace["id"])[0]["id"] == note["id"]
    assert store.search("İŞÇİLİK ALACAĞI", workspace["id"])[0]["id"] == note["id"]
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    reopened = ProductStore(tmp_path)
    assert reopened.list_notes(workspace["id"])[0]["body"] == note["body"]


def test_source_versions_and_workspace_isolation(tmp_path):
    store = ProductStore(tmp_path)
    a, b = store.create_workspace("A"), store.create_workspace("B")
    first = store.save_web_source(a["id"], "https://example.com/law", "Kanun", "Eski metin", "test")
    same = store.save_web_source(a["id"], "https://example.com/law", "Kanun", "Eski metin", "test")
    changed = store.save_web_source(
        a["id"], "https://example.com/law", "Kanun", "Yeni metin", "test"
    )
    assert first["version_id"] == same["version_id"]
    assert first["version_id"] != changed["version_id"]
    assert store.search("kanun", b["id"]) == []
    assert len(store.export(a["id"])["source_versions"]) == 2


def test_restart_never_silently_restarts_running_analysis(tmp_path):
    store = ProductStore(tmp_path)
    job = store.enqueue("analysis", {"url": "https://example.com"})
    assert store.claim_next()["id"] == job["id"]
    store.recover_interrupted()
    recovered = store.get_job(job["id"])
    assert recovered["status"] == "interrupted"
    assert "yeniden" in recovered["error"].lower()


def test_queued_cancel_and_atomic_claim(tmp_path):
    store = ProductStore(tmp_path)
    one = store.enqueue("research", {"query": "a"})
    two = store.enqueue("research", {"query": "b"})
    assert store.cancel(one["id"])["status"] == "cancelled"
    assert store.claim_next()["id"] == two["id"]
    assert store.claim_next() is None
    assert store.cancel(two["id"])["status"] == "cancel_requested"


def test_source_article_dedupe_and_import_ledger(tmp_path):
    store = ProductStore(tmp_path)
    snapshot = {
        "sources": [{"id": "old", "name": "RSS", "url": "https://example.com/feed", "type": "rss"}],
        "articles": [
            {
                "id": "a",
                "source_id": "old",
                "title": "Haber",
                "url": "https://example.com/haber",
                "summary": "İş hukuku",
            }
        ],
    }
    first = store.import_snapshot(snapshot, "fixture-sha256")
    second = store.import_snapshot(snapshot, "fixture-sha256")
    assert first["articles"] == 1
    assert second["already_imported"] is True
    assert store.counts()["articles"] == 1


def test_settings_whitelist_and_export_cannot_escape_workspace(tmp_path):
    store = ProductStore(tmp_path)
    a, b = store.create_workspace("A"), store.create_workspace("B")
    store.save_note(b["id"], "Özel B", "B içeriği")
    with pytest.raises(ValueError):
        store.save_settings({"motor_kok": "C:/evil"})
    with pytest.raises(ValueError):
        store.save_note("missing", "X", "Y")
    assert store.export(a["id"])["notes"] == []
    assert store.save_settings({"theme": "dark"})["theme"] == "dark"


def test_feed_failure_retains_last_success_and_exposes_stale_error(tmp_path):
    store = ProductStore(tmp_path)
    feed = store.upsert_feed("RSS", "https://example.com/feed")
    assert store.list_feeds()[0]["freshness"] == "never_refreshed"
    store.mark_feed(feed["id"])
    success = store.list_feeds()[0]["last_refreshed_at"]
    store.mark_feed(feed["id"], "HTTP timeout")
    current = store.list_feeds()[0]
    assert current["last_refreshed_at"] == success
    assert current["freshness"] == "error"


def test_source_edit_preserves_identity_history_and_metadata(tmp_path):
    store = ProductStore(tmp_path)
    feed = store.upsert_feed(
        "Eski ad", "https://example.org/feed", metadata={"origin": "radar", "category": "hukuk"}
    )
    store.add_articles(feed["id"], [{"title": "Haber", "url": "https://example.org/1"}])
    store.mark_feed(feed["id"])
    before = store.list_feeds()[0]
    updated = store.update_feed(feed["id"], name="Yeni ad", enabled=False)
    assert updated["id"] == feed["id"] and updated["enabled"] is False
    assert updated["article_count"] == 1 and updated["supported"] is True
    assert updated["metadata"].items() >= feed["metadata"].items()
    assert updated["metadata"]["config_revision"]
    assert updated["last_refreshed_at"] == before["last_refreshed_at"]
    assert store.upsert_feed("Yeni ad", feed["url"])["metadata"].items() >= feed["metadata"].items()
    store.record_feed_attempt(feed["id"])
    changed = store.update_feed(feed["id"], url="https://example.org/new", category="teknoloji")
    assert changed["last_refreshed_at"] is None and changed["last_error"] is None
    assert "next_attempt_at" not in changed["metadata"]
    assert changed["category"] == "teknoloji" and changed["metadata"]["origin"] == "radar"
    assert store.list_articles()[0]["source_id"] == feed["id"]
    other = store.upsert_feed("Başka", "https://example.org/other")
    with pytest.raises(ValueError, match="zaten"):
        store.update_feed(feed["id"], url=other["url"])
    assert store.list_articles()[0]["source_id"] == feed["id"]
    with pytest.raises(ValueError, match="boş"):
        store.update_feed(feed["id"], name="  ")
    with pytest.raises(ValueError, match="bulunamadı"):
        store.update_feed("missing", enabled=False)
    legacy = store.upsert_feed("Özel", "https://example.org/custom", "unknown_legacy")
    assert not legacy["supported"]
    assert store.update_feed(legacy["id"], enabled=False)["enabled"] is False


def test_source_categories_import_and_non_destructive_startup_backfill(tmp_path):
    store = ProductStore(tmp_path)
    known = store.upsert_feed("Hukuk", "https://hukukihaber.net/rss", metadata={"lang": "tr"})
    custom = store.upsert_feed("Lexpera", "https://blog.lexpera.com.tr/feed/", category="kişisel")
    unknown = store.upsert_feed("Bilinmeyen", "https://example.org/feed")
    reopened = ProductStore(tmp_path)
    sources = {row["id"]: row for row in reopened.list_feeds()}
    assert sources[known["id"]]["metadata"] == {"lang": "tr", "category": "turk_hukuku"}
    assert sources[custom["id"]]["category"] == "kişisel"
    assert sources[unknown["id"]]["metadata"] == {}
    assert ProductStore(tmp_path).list_feeds() == reopened.list_feeds()
    store.import_snapshot(
        {
            "sources": [
                {
                    "id": "import",
                    "name": "Yeni",
                    "url": "https://example.org/import",
                    "category": "legaltech",
                }
            ]
        },
        "categories-test",
    )
    assert (
        next(row for row in store.list_feeds() if row["id"] == "import")["category"] == "legaltech"
    )


def test_article_page_filters_before_pagination_and_keeps_decision_dates(tmp_path):
    store = ProductStore(tmp_path)
    old = store.upsert_feed("Hukuk", "https://example.org/hukuk", category="turk_hukuku")
    other = store.upsert_feed("AI", "https://example.org/ai", category="dunya_ai")
    store.add_articles(
        old["id"],
        [
            {
                "title": f"İŞÇİLİK kararı {i}",
                "url": f"https://example.org/karar/{i}",
                "published_at": None,
                "provenance": {"decision_date": "2020-01-02"},
            }
            for i in range(3)
        ],
    )
    store.add_articles(
        other["id"],
        [
            {
                "title": f"AI haberi {i}",
                "url": f"https://example.org/ai/{i}",
                "published_at": "2026-01-01",
            }
            for i in range(210)
        ],
    )
    page = store.article_page(source_id=old["id"], category="turk_hukuku", query="iscilik", limit=2)
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["source_name"] == "Hukuk"
    assert page["items"][0]["published_at"] is None
    second = store.article_page(source_id=old["id"], query="İŞÇİLİK", limit=2, offset=2)
    assert second["total"] == 3 and len(second["items"]) == 1
    assert not {r["id"] for r in page["items"]} & {r["id"] for r in second["items"]}
    assert store.article_page(query="%")["total"] == 0
    assert store.article_page(source_id=old["id"], days=1)["total"] == 0
    assert store.article_page(category="missing")["total"] == 0


def test_articles_use_decision_date_when_publication_is_unknown(tmp_path):
    store = ProductStore(tmp_path)
    store.add_articles(
        None,
        [
            {
                "title": "Yeni karar",
                "url": "https://mevzuat.adalet.gov.tr/ictihat/2",
                "published_at": None,
                "provenance": {"decision_date": "2026-09-23", "date_kind": "decision"},
            },
            {
                "title": "Eski karar",
                "url": "https://mevzuat.adalet.gov.tr/ictihat/1",
                "published_at": None,
                "provenance": {"decision_date": "2026-09-01", "date_kind": "decision"},
            },
        ],
    )
    rows = store.list_articles()
    assert [row["title"] for row in rows] == ["Yeni karar", "Eski karar"]
    assert all(row["published_at"] is None for row in rows)


def test_articles_keep_legislation_publication_and_unknown_date_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("rasathane.product.store.now", lambda: "2026-10-04T12:00:00+00:00")
    store = ProductStore(tmp_path)
    store.add_articles(
        None,
        [
            {
                "title": "Karar",
                "url": "https://mevzuat.adalet.gov.tr/ictihat/2",
                "published_at": None,
                "provenance": {"decision_date": "2026-09-23", "date_kind": "decision"},
            },
            {
                "title": "Düzenleme",
                "url": "https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm",
                "published_at": "2026-10-03",
                "provenance": {"date_kind": "publication"},
            },
            {"title": "Tarihsiz kayıt", "url": "https://example.com/unknown"},
        ],
    )
    rows = store.list_articles()
    assert [row["title"] for row in rows] == ["Tarihsiz kayıt", "Düzenleme", "Karar"]
    assert rows[1]["published_at"] == "2026-10-03"
    assert rows[0]["created_at"] == "2026-10-04T12:00:00+00:00"


def test_article_date_order_does_not_change_note_created_order(tmp_path, monkeypatch):
    stamp = {"value": "2026-10-01T12:00:00+00:00"}
    monkeypatch.setattr("rasathane.product.store.now", lambda: stamp["value"])
    store = ProductStore(tmp_path)
    workspace = store.create_workspace("Notlar")
    old = store.save_note(workspace["id"], "Eski not", "Birinci kayıt")
    stamp["value"] = "2026-10-02T12:00:00+00:00"
    new = store.save_note(workspace["id"], "Yeni not", "İkinci kayıt")
    store.add_articles(
        None,
        [
            {
                "title": "Yayın",
                "url": "https://example.com/publication",
                "published_at": "2030-01-01",
            }
        ],
    )
    notes = store.list_notes(workspace["id"])
    assert [note["id"] for note in notes] == [new["id"], old["id"]]
    assert notes[0]["created_at"] == "2026-10-02T12:00:00+00:00"


def test_import_merges_existing_feed_id_and_url_without_losing_current_notes(tmp_path):
    store = ProductStore(tmp_path)
    feed = store.upsert_feed("Güncel kaynak", "https://example.com/rss", feed_id="new-id")
    workspace = store.create_workspace("Araştırma")
    note = store.save_note(workspace["id"], "Korunacak not", "İşçilik araştırması")
    snapshot = {
        "sources": [{"id": "old-id", "name": "Eski kaynak", "url": feed["url"]}],
        "articles": [
            {
                "id": "article",
                "source_id": "old-id",
                "title": "Kıdem tazminatı",
                "url": "https://example.com/article",
                "summary": "İşçilik alacağı",
            }
        ],
    }
    receipt = import_radar_snapshot(store, snapshot)
    assert receipt["inserted_counts"] == {"sources": 0, "articles": 1, "library": 0}
    assert store.list_articles()[0]["source_id"] == "new-id"
    assert store.search("iscilik", workspace["id"])
    assert store.list_notes()[0]["id"] == note["id"]
    assert store.list_feeds()[0]["name"] == "Güncel kaynak"
    assert import_radar_snapshot(store, snapshot)["already_imported"]


def test_import_identity_collision_rolls_back_everything(tmp_path):
    store = ProductStore(tmp_path)
    feed = store.upsert_feed("RSS", "https://example.com/feed", feed_id="shared-id")
    snapshot = {
        "sources": [
            {"id": "shared-id", "name": "Diğer", "url": "https://example.com/other"},
            {"id": "new", "name": "Yeni", "url": "https://example.com/new"},
        ]
    }
    with pytest.raises(ValueError, match="çakışma"):
        import_radar_snapshot(store, snapshot)
    assert store.counts()["sources"] == 1
    assert store.list_feeds()[0]["url"] == feed["url"]
    assert store.rows("SELECT * FROM migration_ledger") == []


def test_readonly_radar_snapshot_never_commits_or_writes_source(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE sources(id,name,url,type,category,enabled,is_user_disabled,
                fetch_interval_minutes,metadata);
            CREATE TABLE articles(id,source_id,title,url,summary,summary_tr_short,published_at);
            CREATE TABLE library_items(id,item_type,snapshot_md,snapshot_meta,note,saved_at);
            INSERT INTO sources VALUES('s','RSS','https://example.com/rss','rss',NULL,
                1,0,180,NULL);
            INSERT INTO articles VALUES('a','s','Kıdem','https://example.com/law',
                'Summary','İşçilik',NULL);
        """)
    before = path.read_bytes()

    class ReadOnlyConnection:
        def __init__(self):
            self.raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            self.closed = False
            self.readonly = False

        def set_session(self, *, readonly, isolation_level, autocommit):
            self.readonly = readonly and isolation_level == "REPEATABLE READ" and not autocommit

        def cursor(self):
            return closing(self.raw.cursor())

        def rollback(self):
            self.raw.rollback()

        def close(self):
            self.closed = True
            self.raw.close()

    connection = ReadOnlyConnection()
    snapshot = read_radar_postgres(lambda: connection)
    assert snapshot["articles"][0]["summary_tr_short"] == "İşçilik"
    assert connection.closed and connection.readonly
    assert path.read_bytes() == before


def test_schema_upgrade_rebuilds_rowid_index_and_rejects_future_database(tmp_path):
    store = ProductStore(tmp_path)
    space = store.create_workspace("İşçilik")
    note = store.save_note(space["id"], "Kıdem", "Alacak")
    with store.connection() as conn:
        conn.execute("UPDATE documents_fts SET rowid=99 WHERE id=?", (note["id"],))
        conn.execute("PRAGMA user_version=1")
    reopened = ProductStore(tmp_path)
    assert reopened.search("alacak", space["id"])[0]["id"] == note["id"]
    with reopened.connection() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        conn.execute("PRAGMA user_version=50")
    with pytest.raises(ValueError, match="daha yeni"):
        ProductStore(tmp_path)

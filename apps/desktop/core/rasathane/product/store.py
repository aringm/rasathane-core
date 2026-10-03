from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fold(value: str) -> str:
    value = value.replace("ı", "i").replace("İ", "i").casefold()
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "system",
    "web_enabled": True,
    "search_provider": "auto",
    "analysis_profile": "ram8",
    "topic_refresh_minutes": 180,
}


class ProductStore:
    """Tek kullanıcı ürün kaydı; her operasyon ayrı connection/transaction kullanır."""

    def __init__(self, directory: Path | None = None) -> None:
        base = directory or Path(os.environ.get("RASATHANE_DATA_DIR", Path.home() / ".rasathane"))
        base.mkdir(parents=True, exist_ok=True)
        self.directory = base.resolve()
        self.path = self.directory / "rasathane.sqlite3"
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise ValueError("Veri kaydı daha yeni bir Rasathane sürümü gerektiriyor.")
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS workspaces(
                    id TEXT PRIMARY KEY,name TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS notes(
                    id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    title TEXT NOT NULL,body TEXT NOT NULL,created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS feeds(
                    id TEXT PRIMARY KEY,name TEXT NOT NULL,url TEXT NOT NULL,kind TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,metadata TEXT NOT NULL DEFAULT '{}',
                    last_refreshed_at TEXT,last_error TEXT,UNIQUE(url,kind));
                CREATE TABLE IF NOT EXISTS articles(
                    id TEXT PRIMARY KEY,source_id TEXT REFERENCES feeds(id),title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,summary TEXT,published_at TEXT,
                    created_at TEXT NOT NULL,
                    provenance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS source_versions(
                    version_id TEXT PRIMARY KEY,source_id TEXT NOT NULL,url TEXT NOT NULL,
                    title TEXT NOT NULL,body TEXT NOT NULL,content_hash TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL,provider TEXT NOT NULL,provenance TEXT NOT NULL,
                    UNIQUE(source_id,content_hash));
                CREATE TABLE IF NOT EXISTS workspace_sources(
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    version_id TEXT NOT NULL REFERENCES source_versions(version_id),
                    PRIMARY KEY(workspace_id,version_id));
                CREATE TABLE IF NOT EXISTS citations(
                    id TEXT PRIMARY KEY,workspace_id TEXT NOT NULL REFERENCES workspaces(id),
                    version_id TEXT NOT NULL REFERENCES source_versions(version_id),
                    query TEXT NOT NULL,created_at TEXT NOT NULL,
                    UNIQUE(workspace_id,version_id,query));
                CREATE TABLE IF NOT EXISTS documents(
                    id TEXT PRIMARY KEY,kind TEXT NOT NULL,workspace_id TEXT,title TEXT NOT NULL,
                    body TEXT NOT NULL,url TEXT,provenance TEXT NOT NULL,created_at TEXT NOT NULL);
                CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                    id UNINDEXED,title,body,tokenize='unicode61 remove_diacritics 2');
                CREATE TABLE IF NOT EXISTS topics(
                    id TEXT PRIMARY KEY,name TEXT NOT NULL,query TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,last_refreshed_at TEXT,last_error TEXT,
                    new_count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS topic_hits(
                    topic_id TEXT NOT NULL REFERENCES topics(id),url_hash TEXT NOT NULL,
                    payload TEXT NOT NULL,first_seen_at TEXT NOT NULL,
                    PRIMARY KEY(topic_id,url_hash));
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,stage TEXT NOT NULL,
                    request TEXT NOT NULL,result TEXT,error TEXT,created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,cancel_requested INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status,created_at);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS migration_ledger(
                    fingerprint TEXT PRIMARY KEY,imported_at TEXT NOT NULL,source TEXT NOT NULL,
                    counts TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conversations(
                    id TEXT PRIMARY KEY,workspace_id TEXT REFERENCES workspaces(id),
                    title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS research_turns(
                    id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id),created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS research_turns_conversation
                    ON research_turns(conversation_id,created_at);
            """)
            if version < 2:
                self._rebuild_index(conn)
                conn.execute("PRAGMA user_version=2")

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def decoded(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in ("request", "result", "provenance", "metadata", "payload", "counts"):
            if key in data and data[key] is not None:
                data[key] = json.loads(data[key])
        for key in ("enabled", "cancel_requested", "has_result", "body_truncated"):
            if key in data:
                data[key] = bool(data[key])
        if "result" in data and "has_result" not in data:
            data["has_result"] = data["result"] is not None
        return data

    def rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return [
                item for row in conn.execute(sql, params) if (item := self.decoded(row)) is not None
            ]

    def _require_workspace(self, conn: sqlite3.Connection, workspace_id: str | None) -> None:
        if (
            workspace_id is not None
            and not conn.execute("SELECT 1 FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
        ):
            raise ValueError("Çalışma alanı bulunamadı.")

    def _rebuild_index(self, conn: sqlite3.Connection) -> None:
        conn.execute("DELETE FROM documents_fts")
        conn.executemany(
            "INSERT INTO documents_fts(rowid,id,title,body) VALUES(?,?,?,?)",
            (
                (row["rowid"], row["id"], fold(row["title"]), fold(row["body"]))
                for row in conn.execute("SELECT rowid,id,title,body FROM documents")
            ),
        )

    def _document(
        self,
        conn: sqlite3.Connection,
        item_id: str,
        kind: str,
        workspace_id: str | None,
        title: str,
        body: str,
        url: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "kind=excluded.kind,workspace_id=excluded.workspace_id,title=excluded.title,"
            "body=excluded.body,url=excluded.url,provenance=excluded.provenance,"
            "created_at=excluded.created_at",
            (item_id, kind, workspace_id, title, body, url, json_text(provenance or {}), now()),
        )
        document_rowid = conn.execute(
            "SELECT rowid FROM documents WHERE id=?", (item_id,)
        ).fetchone()[0]
        # FTS rowid eşlemesi PK araması sağlar; 16k+ kayıt geçişinde id UNINDEXED
        # sütununda her eklemede tüm FTS'yi taramak karesel maliyet oluşturmaz.
        conn.execute("DELETE FROM documents_fts WHERE rowid=?", (document_rowid,))
        conn.execute(
            "INSERT INTO documents_fts(rowid,id,title,body) VALUES(?,?,?,?)",
            (document_rowid, item_id, fold(title), fold(body)),
        )

    def create_workspace(self, name: str) -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValueError("Çalışma alanı adı boş olamaz.")
        item = {"id": uuid.uuid4().hex, "name": name, "created_at": now()}
        with self.connection() as conn:
            conn.execute("INSERT INTO workspaces VALUES(:id,:name,:created_at)", item)
        return item

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM workspaces ORDER BY created_at DESC")

    def save_note(self, workspace_id: str, title: str, body: str) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ValueError("Not başlığı boş olamaz.")
        item = {
            "id": uuid.uuid4().hex,
            "workspace_id": workspace_id,
            "title": title,
            "body": body,
            "created_at": now(),
            "updated_at": now(),
        }
        with self.connection() as conn:
            self._require_workspace(conn, workspace_id)
            conn.execute(
                "INSERT INTO notes VALUES(:id,:workspace_id,:title,:body,:created_at,:updated_at)",
                item,
            )
            self._document(conn, item["id"], "note", workspace_id, title, body)
        return item

    def list_notes(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM notes"
            + (" WHERE workspace_id=?" if workspace_id else "")
            + " ORDER BY updated_at DESC",
            (workspace_id,) if workspace_id else (),
        )

    def save_web_source(
        self,
        workspace_id: str | None,
        url: str,
        title: str,
        body: str,
        provider: str,
        *,
        query: str = "",
        provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_id = digest(url)
        content_hash = digest(body)
        version_id = digest(f"{source_id}|{content_hash}")
        stamp = now()
        receipt = {
            "url": url,
            "content_hash": content_hash,
            "retrieved_at": stamp,
            "provider": provider,
            "text_scope": "preview",
            **(provenance or {}),
        }
        with self.connection() as conn:
            self._require_workspace(conn, workspace_id)
            conn.execute(
                "INSERT OR IGNORE INTO source_versions VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    version_id,
                    source_id,
                    url,
                    title,
                    body,
                    content_hash,
                    stamp,
                    provider,
                    json_text(receipt),
                ),
            )
            if workspace_id:
                conn.execute(
                    "INSERT OR IGNORE INTO workspace_sources VALUES(?,?)",
                    (workspace_id, version_id),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO citations VALUES(?,?,?,?,?)",
                    (uuid.uuid4().hex, workspace_id, version_id, query, stamp),
                )
            document_id = digest(f"{version_id}|{workspace_id or ''}")
            self._document(conn, document_id, "web_source", workspace_id, title, body, url, receipt)
            actual = self.decoded(
                conn.execute(
                    "SELECT * FROM source_versions WHERE version_id=?", (version_id,)
                ).fetchone()
            )
        assert actual is not None
        return actual

    def search(
        self, query: str, workspace_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        tokens = re.findall(r"\w+", fold(query))[:16]
        if not tokens:
            return []
        expression = " AND ".join('"' + token.replace('"', '""') + '"*' for token in tokens)
        sql = (
            "SELECT d.id,d.kind,d.workspace_id,d.title,substr(d.body,1,4000) AS body,d.url,"
            "json_remove(d.provenance,'$.engine_result') AS provenance,d.created_at,"
            "length(d.body)>4000 AS body_truncated,bm25(documents_fts) AS score FROM documents_fts "
            "JOIN documents d ON d.id=documents_fts.id WHERE documents_fts MATCH ?"
        )
        params: tuple[Any, ...] = (expression,)
        if workspace_id:
            sql += " AND (d.workspace_id=? OR (d.workspace_id IS NULL AND d.kind='article'))"
            params += (workspace_id,)
        sql += " ORDER BY score LIMIT ?"
        return self.rows(sql, (*params, limit))

    def library(self, limit: int = 200, *, brief: bool = False) -> list[dict[str, Any]]:
        fields = (
            "id,kind,workspace_id,title,substr(body,1,2000) AS body,url,"
            "json_remove(provenance,'$.engine_result') AS provenance,created_at,"
            "length(body)>2000 AS body_truncated"
            if brief
            else "*"
        )
        return self.rows(
            f"SELECT {fields} FROM documents WHERE kind!='article' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )

    def add_analysis(self, job_id: str, result: dict[str, Any]) -> None:
        index = result.get("index") or {}
        title = index.get("baslik") or "Analiz"
        body = "\n\n".join(
            str(result.get(k) or "")
            for k in ("ozet_kisa", "ozet_orta", "ozet_detay", "kisisel_analiz")
        )
        receipt = {
            "job_id": job_id,
            "motor": result.get("motor", {}),
            "pii_tespit": result.get("pii_tespit"),
            "content_hash": digest(body),
            "engine_result": result,
        }
        with self.connection() as conn:
            self._document(
                conn,
                job_id,
                "analysis",
                None,
                title,
                body,
                index.get("kaynak_url") or index.get("video_url"),
                receipt,
            )

    def save_bulletin(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Bülten, oluşturulduğu andaki kaynak özetleriyle birlikte yerelde saklanır."""
        with self.connection() as conn:
            self._require_workspace(conn, snapshot.get("workspace_id"))
            self._document(
                conn,
                snapshot["id"],
                "bulletin",
                snapshot.get("workspace_id"),
                snapshot["title"],
                snapshot["summary"],
                provenance={"bulletin": snapshot, "content_hash": snapshot["content_hash"]},
            )
        return self.get_bulletin(snapshot["id"])

    def get_bulletin(self, item_id: str) -> dict[str, Any]:
        rows = self.rows(
            "SELECT provenance FROM documents WHERE id=? AND kind='bulletin'", (item_id,)
        )
        if not rows:
            raise ValueError("Bülten bulunamadı.")
        snapshot: dict[str, Any] = rows[0]["provenance"]["bulletin"]
        return snapshot

    def list_bulletins(self) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT id,title,created_at,workspace_id,"
            "json_extract(provenance,'$.bulletin.article_count') AS article_count,"
            "json_extract(provenance,'$.bulletin.ready_count') AS ready_count "
            "FROM documents WHERE kind='bulletin' ORDER BY created_at DESC,id DESC LIMIT 50"
        )

    def create_topic(self, name: str, query: str) -> dict[str, Any]:
        name, query = name.strip(), query.strip()
        if not name or not query:
            raise ValueError("Konu adı ve sorgusu boş olamaz.")
        topic_id = uuid.uuid4().hex
        with self.connection() as conn:
            conn.execute("INSERT INTO topics(id,name,query) VALUES(?,?,?)", (topic_id, name, query))
        return self.rows("SELECT * FROM topics WHERE id=?", (topic_id,))[0]

    def list_topics(self) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM topics ORDER BY name")

    def get_topic(self, item_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            topic = self.decoded(
                conn.execute("SELECT * FROM topics WHERE id=?", (item_id,)).fetchone()
            )
            if topic is None:
                raise ValueError("Konu takibi bulunamadı.")
            latest = self.decoded(
                conn.execute(
                    "SELECT result FROM jobs WHERE kind='refresh' AND status='completed' "
                    "AND json_extract(request,'$.topic_id')=? "
                    "ORDER BY updated_at DESC,created_at DESC,id DESC LIMIT 1",
                    (item_id,),
                ).fetchone()
            )
        return {"topic": topic, "latest_result": latest["result"] if latest else None}

    def record_topic_hits(self, topic_id: str, hits: list[dict[str, Any]]) -> int:
        inserted = 0
        with self.connection() as conn:
            if not conn.execute("SELECT 1 FROM topics WHERE id=?", (topic_id,)).fetchone():
                raise ValueError("Konu takibi bulunamadı.")
            for hit in hits:
                inserted += conn.execute(
                    "INSERT OR IGNORE INTO topic_hits VALUES(?,?,?,?)",
                    (topic_id, digest(hit["url"]), json_text(hit), now()),
                ).rowcount
            conn.execute(
                "UPDATE topics SET last_refreshed_at=?,last_error=NULL,new_count=? WHERE id=?",
                (now(), inserted, topic_id),
            )
        return inserted

    def topic_error(self, topic_id: str, error: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE topics SET last_error=? WHERE id=?", (error[:500], topic_id))

    def upsert_feed(
        self,
        name: str,
        url: str,
        kind: str = "rss",
        metadata: dict[str, Any] | None = None,
        *,
        feed_id: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM feeds WHERE url=? AND kind=?", (url, kind)
            ).fetchone()
            item_id = existing[0] if existing else (feed_id or uuid.uuid4().hex)
            conn.execute(
                "INSERT INTO feeds(id,name,url,kind,enabled,metadata) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,"
                "metadata=excluded.metadata",
                (item_id, name, url, kind, int(enabled), json_text(metadata or {})),
            )
        return self.rows("SELECT * FROM feeds WHERE id=?", (item_id,))[0]

    def list_feeds(self) -> list[dict[str, Any]]:
        rows = self.rows("SELECT * FROM feeds ORDER BY name")
        for row in rows:
            row["freshness"] = "never_refreshed"
            if row["last_error"]:
                row["freshness"] = "error"
            elif row["last_refreshed_at"]:
                try:
                    stamp = datetime.fromisoformat(row["last_refreshed_at"])
                    stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp
                    minutes = max(15, int(row["metadata"].get("fetch_interval_minutes", 180)))
                    age = (datetime.now(UTC) - stamp).total_seconds()
                    row["freshness"] = "stale" if age > minutes * 60 else "fresh"
                except (ValueError, TypeError):
                    row["freshness"] = "stale"
        return rows

    def add_articles(self, feed_id: str | None, articles: list[dict[str, Any]]) -> int:
        with self.connection() as conn:
            return self._add_articles(conn, feed_id, articles)

    def _add_articles(
        self, conn: sqlite3.Connection, feed_id: str | None, articles: list[dict[str, Any]]
    ) -> int:
        inserted = 0
        for row in articles:
            url = row.get("url", "")
            if not url:
                continue
            item_id = row.get("id") or digest(url)
            title, summary = row.get("title") or "Başlıksız kaynak", row.get("summary") or ""
            receipt = {
                "url": url,
                "retrieved_at": now(),
                "content_hash": digest(title + "\n" + summary),
                **row.get("provenance", {}),
            }
            count = conn.execute(
                "INSERT OR IGNORE INTO articles VALUES(?,?,?,?,?,?,?,?)",
                (
                    item_id,
                    feed_id,
                    title,
                    url,
                    summary,
                    row.get("published_at"),
                    now(),
                    json_text(receipt),
                ),
            ).rowcount
            inserted += count
            if count:
                self._document(conn, item_id, "article", None, title, summary, url, receipt)
        return inserted

    def mark_feed(self, feed_id: str, error: str | None = None) -> None:
        with self.connection() as conn:
            if error:
                conn.execute("UPDATE feeds SET last_error=? WHERE id=?", (error[:500], feed_id))
            else:
                conn.execute(
                    "UPDATE feeds SET last_refreshed_at=?,last_error=NULL WHERE id=?",
                    (now(), feed_id),
                )

    def record_feed_attempt(self, feed_id: str, delay_seconds: int = 600) -> None:
        with self.connection() as conn:
            row = conn.execute("SELECT metadata FROM feeds WHERE id=?", (feed_id,)).fetchone()
            if row is None:
                raise ValueError("Kaynak bulunamadı.")
            metadata = json.loads(row[0])
            stamp = datetime.now(UTC)
            metadata.update(
                {
                    "last_attempt_at": stamp.isoformat(),
                    "next_attempt_at": (
                        stamp + timedelta(seconds=max(60, min(delay_seconds, 86400)))
                    ).isoformat(),
                }
            )
            conn.execute("UPDATE feeds SET metadata=? WHERE id=?", (json_text(metadata), feed_id))

    def list_articles(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM articles ORDER BY "
            "COALESCE(json_extract(provenance,'$.decision_date'),published_at,created_at) DESC "
            "LIMIT ?",
            (limit,),
        )

    def enqueue(self, kind: str, request: dict[str, Any]) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "status": "queued",
            "stage": "queued",
            "request": json_text(request),
            "result": None,
            "error": None,
            "created_at": now(),
            "updated_at": now(),
            "cancel_requested": 0,
        }
        with self.connection() as conn:
            if kind == "research":
                # A turn, conversation and queued job commit together. Its durable job
                # owns status/result, so cancellation and crash recovery cannot diverge.
                conn.execute("BEGIN IMMEDIATE")
                request = dict(request)
                conversation_id = request.get("conversation_id")
                if conversation_id:
                    conversation = conn.execute(
                        "SELECT * FROM conversations WHERE id=?", (conversation_id,)
                    ).fetchone()
                    if conversation is None:
                        raise ValueError("Konuşma bulunamadı.")
                    if request.get("workspace_id") not in (None, conversation["workspace_id"]):
                        raise ValueError("Konuşmanın çalışma alanı değiştirilemez.")
                    request["workspace_id"] = conversation["workspace_id"]
                    if conn.execute(
                        "SELECT 1 FROM research_turns t JOIN jobs j ON j.id=t.job_id "
                        "WHERE t.conversation_id=? AND j.status IN "
                        "('queued','running','cancel_requested')",
                        (conversation_id,),
                    ).fetchone():
                        raise ValueError("Önceki yanıtın tamamlanmasını bekleyin.")
                else:
                    conversation_id = uuid.uuid4().hex
                    self._require_workspace(conn, request.get("workspace_id"))
                    conn.execute(
                        "INSERT INTO conversations VALUES(?,?,?,?,?)",
                        (
                            conversation_id,
                            request.get("workspace_id"),
                            str(request["query"]).strip()[:120],
                            item["created_at"],
                            item["created_at"],
                        ),
                    )
                request.update(conversation_id=conversation_id, turn_id=uuid.uuid4().hex)
                item["request"] = json_text(request)
            conn.execute(
                "INSERT INTO jobs VALUES(:id,:kind,:status,:stage,:request,:result,:error,"
                ":created_at,:updated_at,:cancel_requested)",
                item,
            )
            if kind == "research":
                conn.execute(
                    "INSERT INTO research_turns VALUES(?,?,?,?)",
                    (
                        request["turn_id"],
                        request["conversation_id"],
                        item["id"],
                        item["created_at"],
                    ),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (
                        item["created_at"],
                        request["conversation_id"],
                    ),
                )
        return self.get_job(item["id"])

    def list_conversations(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        return self.rows(
            "SELECT * FROM conversations"
            + (" WHERE workspace_id=?" if workspace_id else "")
            + " ORDER BY updated_at DESC LIMIT 100",
            (workspace_id,) if workspace_id else (),
        )

    def get_conversation(
        self, conversation_id: str, *, before: str | None = None, page_size: int | None = None
    ) -> dict[str, Any]:
        conversations = self.rows("SELECT * FROM conversations WHERE id=?", (conversation_id,))
        if not conversations:
            raise ValueError("Konuşma bulunamadı.")
        messages = []
        where = "t.conversation_id=?"
        params: tuple[Any, ...] = (conversation_id,)
        if before is not None:
            cursor = self.rows(
                "SELECT created_at,job_id FROM research_turns WHERE id=? AND conversation_id=?",
                (before, conversation_id),
            )
            if not cursor:
                raise ValueError("Konuşma sayfa imleci geçersiz.")
            where += " AND (t.created_at,j.id)<(?,?)"
            params += (cursor[0]["created_at"], cursor[0]["job_id"])
        fields = "j.*"
        if page_size is not None:
            from rasathane.product.research_chat import CHAT_RESULT_FIELDS

            page_size = max(1, min(50, page_size))
            # Project in SQLite before decoding: historical fetched bodies can be
            # megabytes per turn and must not be loaded just to reopen chat.
            projection = ",".join(
                f"'{key}',json_extract(j.result,'$.{key}')" for key in CHAT_RESULT_FIELDS
            )
            fields = (
                f"j.id,j.status,j.error,j.created_at,j.request,json_object({projection}) AS result"
            )
        jobs = self.rows(
            f"SELECT {fields},t.id AS turn_id FROM research_turns t JOIN jobs j ON j.id=t.job_id "
            f"WHERE {where} ORDER BY t.created_at DESC,j.id DESC"
            + (" LIMIT ?" if page_size else ""),
            (*params, page_size + 1) if page_size else params,
        )
        has_more = page_size is not None and len(jobs) > page_size
        jobs = jobs[:page_size] if page_size is not None else jobs
        jobs.reverse()
        for job in jobs:
            common = {
                "job_id": job["id"],
                "turn_id": job["turn_id"],
                "created_at": job["created_at"],
            }
            messages.append(
                {
                    **common,
                    "id": job["turn_id"] + ":user",
                    "role": "user",
                    "content": job["request"]["query"],
                    "status": "completed",
                }
            )
            result = job["result"] or {}
            if page_size is not None:
                from rasathane.product.research_chat import compact_chat_result

                result = compact_chat_result(result)
            messages.append(
                {
                    **common,
                    "id": job["turn_id"] + ":assistant",
                    "role": "assistant",
                    "content": result.get("answer") or job["error"] or "",
                    "status": job["status"],
                    "result": result,
                }
            )
        return {
            **conversations[0],
            "messages": messages,
            "next_before": jobs[0]["turn_id"] if has_more else None,
        }

    def cancel_pending_jobs(self) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status=CASE WHEN status='queued' THEN 'cancelled' "
                "ELSE 'cancel_requested' END,cancel_requested=1,updated_at=? "
                "WHERE status IN ('queued','running','cancel_requested')",
                (now(),),
            )

    def latest_conversation_citations(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT json_extract(j.result,'$.citations') FROM research_turns t "
                "JOIN jobs j ON j.id=t.job_id WHERE t.conversation_id=? AND j.status='completed' "
                "ORDER BY t.created_at DESC,j.id DESC LIMIT 1",
                (conversation_id,),
            ).fetchone()
        return json.loads(row[0]) if row and row[0] else []

    def get_job(self, job_id: str) -> dict[str, Any]:
        rows = self.rows("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not rows:
            raise ValueError("İş bulunamadı.")
        return rows[0]

    def completed_artifact(self, path: str) -> dict[str, Any] | None:
        """Büyük analiz gövdelerini yüklemeden tam yolun çıktı makbuzunu getir."""
        collate = " COLLATE NOCASE" if os.name == "nt" else ""
        with self.connection() as conn:
            row = conn.execute(
                "SELECT json_extract(a.value,'$.path') AS path,"
                "json_extract(a.value,'$.name') AS name,"
                "json_extract(a.value,'$.bytes') AS bytes,"
                "json_extract(a.value,'$.sha256') AS sha256,"
                "json_extract(j.result,'$.klasor') AS folder "
                "FROM jobs AS j,json_each(j.result,'$.artifacts') AS a "
                "WHERE j.kind='analysis' AND j.status='completed' "
                f"AND json_extract(a.value,'$.path')=?{collate} "
                "ORDER BY j.created_at DESC LIMIT 1",
                (path,),
            ).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 100, *, brief: bool = False) -> list[dict[str, Any]]:
        fields = (
            "id,kind,status,stage,request,NULL AS result,result IS NOT NULL AS has_result,"
            "error,created_at,updated_at,cancel_requested"
            if brief
            else "*"
        )
        return self.rows(f"SELECT {fields} FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))

    def claim_next(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute(
                "SELECT 1 FROM jobs WHERE status IN ('running','cancel_requested')"
            ).fetchone():
                return None
            row = conn.execute(
                "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET status='running',stage='starting',updated_at=? WHERE id=?",
                (now(), row["id"]),
            )
            return self.decoded(
                conn.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            )

    def update_job(
        self,
        job_id: str,
        status: str | None = None,
        *,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        with self.connection() as conn:
            current = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if current is None:
                raise ValueError("İş bulunamadı.")
            desired = status or current["status"]
            if current["cancel_requested"] and desired == "completed":
                desired, result = "cancelled", None
            conn.execute(
                "UPDATE jobs SET status=?,stage=?,result=?,error=?,updated_at=? WHERE id=?",
                (
                    desired,
                    stage or desired,
                    json_text(result) if result is not None else current["result"],
                    error,
                    now(),
                    job_id,
                ),
            )

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise ValueError("İş bulunamadı.")
            if row["status"] in ("queued", "running", "cancel_requested"):
                status = "cancelled" if row["status"] == "queued" else "cancel_requested"
                conn.execute(
                    "UPDATE jobs SET status=?,cancel_requested=1,updated_at=? WHERE id=?",
                    (status, now(), job_id),
                )
        return self.get_job(job_id)

    def recover_interrupted(self) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' "
                "ELSE 'interrupted' END,stage='restart',error=?,updated_at=? "
                "WHERE status IN ('running','cancel_requested')",
                (
                    "Uygulama kapandı; ücretli veya pahalı işlem otomatik yeniden başlatılmadı.",
                    now(),
                ),
            )

    def settings(self) -> dict[str, Any]:
        result = dict(DEFAULT_SETTINGS)
        with self.connection() as conn:
            result.update(
                {
                    row["key"]: json.loads(row["value"])
                    for row in conn.execute("SELECT * FROM settings")
                }
            )
        return result

    def save_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict) or set(data) - set(DEFAULT_SETTINGS):
            raise ValueError("Desteklenmeyen ayar alanı.")
        choices = {
            "theme": {"dark", "light", "system"},
            "search_provider": {"auto", "duckduckgo", "configured"},
            "analysis_profile": {"ram8", "ram16", "auto"},
        }
        for key, value in data.items():
            if key in choices and (not isinstance(value, str) or value not in choices[key]):
                raise ValueError(f"Geçersiz ayar: {key}")
            if key == "web_enabled" and not isinstance(value, bool):
                raise ValueError("web_enabled boolean olmalı.")
            if key == "topic_refresh_minutes" and (
                type(value) is not int or value < 0 or value > 10080 or 0 < value < 15
            ):
                raise ValueError("Yenileme aralığı 0 (kapalı) veya 15–10080 dakika olmalı.")
        with self.connection() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                [(key, json_text(value)) for key, value in data.items()],
            )
        return self.settings()

    def counts(self) -> dict[str, int]:
        with self.connection() as conn:
            result = {
                key: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for key, table in (
                    ("sources", "feeds"),
                    ("articles", "articles"),
                    ("workspaces", "workspaces"),
                    ("notes", "notes"),
                    ("topics", "topics"),
                )
            }
            result["library"] = conn.execute(
                "SELECT count(*) FROM documents WHERE kind!='article'"
            ).fetchone()[0]
        return result

    def export(self, workspace_id: str | None = None) -> dict[str, Any]:
        with self.connection() as conn:
            self._require_workspace(conn, workspace_id)
        payload: dict[str, Any] = {
            "product": "Rasathane",
            "schema_version": 1,
            "exported_at": now(),
            "workspace_id": workspace_id,
        }
        for table in ("workspaces", "notes", "citations", "documents"):
            field = "id" if table == "workspaces" else "workspace_id"
            payload[table] = self.rows(
                f"SELECT * FROM {table}" + (f" WHERE {field}=?" if workspace_id else ""),
                (workspace_id,) if workspace_id else (),
            )
        payload["source_versions"] = self.rows(
            "SELECT v.* FROM source_versions v"
            + (
                " JOIN workspace_sources w ON w.version_id=v.version_id WHERE w.workspace_id=?"
                if workspace_id
                else ""
            ),
            (workspace_id,) if workspace_id else (),
        )
        payload["conversations"] = [
            self.get_conversation(row["id"])
            for row in self.rows(
                "SELECT id FROM conversations" + (" WHERE workspace_id=?" if workspace_id else ""),
                (workspace_id,) if workspace_id else (),
            )
        ]
        if not workspace_id:
            for table in ("feeds", "articles", "topics", "topic_hits", "jobs", "migration_ledger"):
                payload[table] = self.rows(f"SELECT * FROM {table}")
            payload["settings"] = self.settings()
        payload["content_hash"] = digest(json_text(payload))
        return payload

    def import_snapshot(
        self, snapshot: dict[str, Any], fingerprint: str, source: str = "radar-readonly"
    ) -> dict[str, Any]:
        """İçe aktarma dıştaki migration transaction'ında atomik; tekrarlar ledger ile kesilir."""
        existing = self.rows("SELECT * FROM migration_ledger WHERE fingerprint=?", (fingerprint,))
        if existing:
            return {"already_imported": True, **existing[0]["counts"]}
        # Yerel operasyonların ayrı connection açması nedeniyle staging DB'de transaction
        # kurulur; yalnız tam ve integrity-checked migration canonical DB'ye attach edilir.
        staging = ProductStore(self.directory / ("import-" + digest(fingerprint)[:16]))
        ids = {}
        for row in snapshot.get("sources", []):
            kind = row.get("kind") or row.get("type") or "rss"
            feed = staging.upsert_feed(
                row.get("name") or "Kaynak",
                row["url"],
                kind,
                {
                    **(row.get("metadata") or {}),
                    "fetch_interval_minutes": row.get("fetch_interval_minutes", 180),
                },
                feed_id=str(row["id"]),
                enabled=bool(row.get("enabled", True))
                and not bool(row.get("is_user_disabled", False)),
            )
            ids[str(row["id"])] = feed["id"]
        # Tüm article'lar tek staging transaction'ında; 16k+ kayıtta connection/WAL
        # açılışını her satır için tekrar etmek yerine büyük geçişi de hafif tutar.
        with staging.connection() as conn:
            for row in snapshot.get("articles", []):
                staging._add_articles(
                    conn,
                    ids.get(str(row.get("source_id"))),
                    [
                        {
                            **row,
                            "id": str(row["id"]),
                            "summary": row.get("summary_tr_short") or row.get("summary") or "",
                            "provenance": {"import": source, "source_fingerprint": fingerprint},
                        }
                    ],
                )
        for row in snapshot.get("library_items", []):
            with staging.connection() as conn:
                staging._document(
                    conn,
                    str(row["id"]),
                    "legacy_library",
                    None,
                    (row.get("snapshot_meta") or {}).get("title") or "Radar kaydı",
                    row.get("snapshot_md") or "",
                    provenance={"legacy": row, "source_fingerprint": fingerprint},
                )
        input_counts = {
            "sources": len(snapshot.get("sources", [])),
            "articles": len(snapshot.get("articles", [])),
            "library": len(snapshot.get("library_items", [])),
        }
        staged_counts = staging.counts()
        counts: dict[str, Any] = {
            key: staged_counts[key] for key in ("sources", "articles", "library")
        }
        counts["input_counts"] = input_counts
        with staging.connection() as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Geçiş kayıtlarının SQLite bütünlük kontrolü başarısız.")
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Geçiş kayıtları geçersiz kaynak referansı içeriyor.")
        with self.connection() as conn:
            conn.execute("ATTACH DATABASE ? AS legacy_import", (str(staging.path),))
            conn.execute("BEGIN IMMEDIATE")
            # Bir kullanıcı geçişten önce aynı feed'i eklemiş olabilir. Eski UUID'yi
            # körlemesine article FK'sı olarak taşımak yerine URL/kind kimliğini eşleştir.
            # Mevcut yeni kayıtlar korunur; kimlik çakışması sessiz veri kaybı yerine rollback.
            existing = conn.execute(
                "SELECT counts FROM migration_ledger WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if existing:
                return {"already_imported": True, **json.loads(existing[0])}
            inserted = {}
            for key, table in (
                ("sources", "feeds"),
                ("articles", "articles"),
                ("library", "documents"),
            ):
                where = " WHERE kind!='article'" if key == "library" else ""
                inserted[key] = conn.execute(f"SELECT count(*) FROM {table}{where}").fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO feeds SELECT * FROM legacy_import.feeds")
            missing_feed = conn.execute(
                "SELECT 1 FROM legacy_import.feeds l LEFT JOIN feeds f "
                "ON f.url=l.url AND f.kind=l.kind WHERE f.id IS NULL LIMIT 1"
            ).fetchone()
            if missing_feed:
                raise ValueError("Kaynak kimlik çakışması; geçiş geri alındı.")
            conn.execute(
                "INSERT OR IGNORE INTO articles SELECT l.id,f.id,l.title,l.url,l.summary,"
                "l.published_at,l.created_at,l.provenance FROM legacy_import.articles l "
                "LEFT JOIN legacy_import.feeds old ON old.id=l.source_id "
                "LEFT JOIN feeds f ON f.url=old.url AND f.kind=old.kind"
            )
            missing_article = conn.execute(
                "SELECT 1 FROM legacy_import.articles l LEFT JOIN articles a "
                "ON a.url=l.url WHERE a.id IS NULL LIMIT 1"
            ).fetchone()
            if missing_article:
                raise ValueError("Article kimlik çakışması; geçiş geri alındı.")
            conn.execute(
                "INSERT OR IGNORE INTO documents SELECT a.id,l.kind,l.workspace_id,l.title,"
                "l.body,l.url,l.provenance,l.created_at FROM legacy_import.documents l "
                "JOIN articles a ON a.url=l.url WHERE l.kind='article'"
            )
            conn.execute(
                "INSERT OR IGNORE INTO documents SELECT * FROM legacy_import.documents "
                "WHERE kind!='article'"
            )
            # Canonical rowid'ler staging ile aynı değildir. FTS yalnız türetilmiş
            # index'tir; taşınan ve önceden bulunan belgeyi aynı transaction'da yeniden kur.
            self._rebuild_index(conn)
            for key, table in (
                ("sources", "feeds"),
                ("articles", "articles"),
                ("library", "documents"),
            ):
                where = " WHERE kind!='article'" if key == "library" else ""
                after = conn.execute(f"SELECT count(*) FROM {table}{where}").fetchone()[0]
                inserted[key] = after - inserted[key]
            counts["inserted_counts"] = inserted
            conn.execute(
                "INSERT INTO migration_ledger VALUES(?,?,?,?)",
                (fingerprint, now(), source, json_text(counts)),
            )
        return {"already_imported": False, **counts}

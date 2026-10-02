"""Tests for the Rasathane MCP server.

Tools are tested by calling them as plain async functions (FastMCP keeps
the decorated callable invokable). DB access is mocked at the session
level — we don't exercise SQL semantics here, that's SQLAlchemy's job.
The interesting surface is serialization, input validation, error paths,
and filesystem reads (get_brief).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from ingestion.muhakeme_mcp import EmsalHit, MuhakemeNotConfiguredError
from rasathane_mcp import server as mcp_server
from rasathane_mcp.core import articles as core_articles
from rasathane_mcp.core import sources as core_sources
from rasathane_mcp.core import stats as core_stats

# ── Fakes ──────────────────────────────────────────────────────────────


class _FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)


class _FakeResult:
    """Subset of SQLAlchemy ``Result`` we use in tools."""

    def __init__(
        self,
        *,
        scalars: list[Any] | None = None,
        rows: list[Any] | None = None,
        scalar_value: Any = None,
    ) -> None:
        self._scalars = scalars or []
        self._rows = rows or []
        self._scalar = scalar_value

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars)

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one(self) -> Any:
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return self._scalar


class _FakeSession:
    def __init__(self, results: list[_FakeResult]) -> None:
        self._results = list(results)
        self.executed_statements: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed_statements.append(stmt)
        if not self._results:
            raise AssertionError("FakeSession exhausted — under-mocked test")
        return self._results.pop(0)


class _FakeSessionFactory:
    """Replacement for ``store.database.session_factory``."""

    def __init__(self, results: list[_FakeResult]) -> None:
        self._session = _FakeSession(results)
        self.entered = 0

    def __call__(self) -> _FakeSessionFactory:
        return self

    async def __aenter__(self) -> _FakeSession:
        self.entered += 1
        return self._session

    async def __aexit__(self, *args: object) -> None:
        return None


def _fake_source(
    *,
    name: str = "Sample Source",
    category: str = "dunya_ai",
    type: str = "rss",  # noqa: A002 — mirrors Source.type field name
    url: str = "https://example.com/feed",
    enabled: bool = True,
    is_user_disabled: bool = False,
) -> Any:
    """Duck-typed Source row."""
    s = MagicMock()
    s.id = uuid.uuid4()
    s.name = name
    s.category = category
    s.type = type
    s.url = url
    s.enabled = enabled
    s.is_user_disabled = is_user_disabled
    s.fetch_interval_minutes = 60
    s.last_fetched_at = datetime(2026, 5, 6, 12, 0, 0, tzinfo=UTC)
    s.metadata_ = {"lang": "en"}
    return s


def _fake_article(
    *,
    title: str = "Sample article",
    summary: str = "Short summary",
    url: str = "https://example.com/article",
    source: Any = None,
    has_embedding: bool = False,
) -> Any:
    a = MagicMock()
    a.url = url
    a.title = title
    a.summary = summary
    a.author = "anon"
    a.published_at = datetime(2026, 5, 6, 14, 0, 0, tzinfo=UTC)
    a.fetched_at = datetime(2026, 5, 6, 15, 0, 0, tzinfo=UTC)
    a.metadata_ = {"feed_url": url}
    a.embedding = [0.1] * 1024 if has_embedding else None
    a.source = source or _fake_source()
    return a


# ── list_sources ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_sources_returns_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    src = _fake_source(name="Anthropic News", category="dunya_ai")
    factory = _FakeSessionFactory([_FakeResult(scalars=[src])])
    monkeypatch.setattr(core_sources, "session_factory", factory)

    rows = await mcp_server.list_sources(category="dunya_ai")
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Anthropic News"
    assert row["category"] == "dunya_ai"
    assert row["type"] == "rss"
    assert row["enabled"] is True
    assert row["last_fetched_at"] == "2026-05-06T12:00:00+00:00"
    assert factory.entered == 1


@pytest.mark.asyncio
async def test_list_sources_serializes_user_disabled_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-disabled sources surface ``effective_enabled=False`` even if base is True."""
    src = _fake_source(name="Muted feed", enabled=True, is_user_disabled=True)
    monkeypatch.setattr(
        core_sources, "session_factory", _FakeSessionFactory([_FakeResult(scalars=[src])])
    )

    rows = await mcp_server.list_sources(enabled_only=False)
    assert len(rows) == 1
    row = rows[0]
    assert row["enabled"] is True  # feeds.yaml flag preserved
    assert row["is_user_disabled"] is True
    assert row["effective_enabled"] is False  # override wins


@pytest.mark.asyncio
async def test_list_sources_empty_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_sources, "session_factory", _FakeSessionFactory([_FakeResult(scalars=[])])
    )
    assert await mcp_server.list_sources() == []


# ── recent_articles ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recent_articles_serializes_with_source(monkeypatch: pytest.MonkeyPatch) -> None:
    src = _fake_source(name="r/LocalLLaMA", category="muhakeme_stack", type="reddit")
    art = _fake_article(title="Qwen 3.6 inference 2.5x faster", source=src)
    monkeypatch.setattr(
        core_articles,
        "session_factory",
        _FakeSessionFactory([_FakeResult(scalars=[art])]),
    )

    rows = await mcp_server.recent_articles(category="muhakeme_stack", since_hours=24)
    assert len(rows) == 1
    row = rows[0]
    assert row["title"] == "Qwen 3.6 inference 2.5x faster"
    assert row["source"]["name"] == "r/LocalLLaMA"
    assert row["source"]["type"] == "reddit"
    assert "fetched_at" in row
    assert "similarity" not in row  # only set for search


@pytest.mark.asyncio
async def test_recent_articles_clamps_oversized_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_articles,
        "session_factory",
        _FakeSessionFactory([_FakeResult(scalars=[])]),
    )
    # Sanity: oversized request shouldn't raise; just clamps internally.
    result = await mcp_server.recent_articles(limit=10_000)
    assert result == []


@pytest.mark.asyncio
async def test_recent_articles_promotes_zero_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_articles,
        "session_factory",
        _FakeSessionFactory([_FakeResult(scalars=[])]),
    )
    result = await mcp_server.recent_articles(since_hours=0, limit=0)
    assert result == []


# ── search_articles ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_articles_returns_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
    art = _fake_article(title="Türkçe NER paper", has_embedding=True)
    # search_articles fetches (Article, distance) tuples.
    rows = [(art, 0.18)]
    monkeypatch.setattr(
        core_articles,
        "session_factory",
        _FakeSessionFactory([_FakeResult(rows=rows)]),
    )

    fake_embed = AsyncMock(return_value=[[0.1] * 1024])
    monkeypatch.setattr(core_articles, "embed_batch", fake_embed)

    results = await mcp_server.search_articles("Türkçe NER", top_k=5)
    assert len(results) == 1
    assert results[0]["similarity"] == pytest.approx(0.82, abs=0.001)
    fake_embed.assert_awaited_once_with(["Türkçe NER"])


@pytest.mark.asyncio
async def test_search_articles_empty_query_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No DB hit, no embed call when query is empty."""
    fake_embed = AsyncMock()
    monkeypatch.setattr(core_articles, "embed_batch", fake_embed)
    # Don't even need a session factory — the early-return prevents touching it.
    monkeypatch.setattr(core_articles, "session_factory", _FakeSessionFactory([]))

    assert await mcp_server.search_articles("   ") == []
    fake_embed.assert_not_called()


@pytest.mark.asyncio
async def test_search_articles_clamps_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        core_articles,
        "session_factory",
        _FakeSessionFactory([_FakeResult(rows=[])]),
    )
    monkeypatch.setattr(core_articles, "embed_batch", AsyncMock(return_value=[[0.0] * 1024]))
    out = await mcp_server.search_articles("anything", top_k=9999)
    assert out == []


# ── get_brief ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_brief_returns_error_when_archive_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", tmp_path / "nope")
    result = await mcp_server.get_brief()
    assert "error" in result
    assert "archive directory" in result["error"]


@pytest.mark.asyncio
async def test_get_brief_returns_error_when_archive_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", archive)
    result = await mcp_server.get_brief()
    assert "error" in result
    assert "no briefs found" in result["error"]


@pytest.mark.asyncio
async def test_get_brief_default_returns_latest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    for d, body in [
        ("2026-05-04", "# Older brief"),
        ("2026-05-06", "# Newer brief"),
        ("2026-05-05", "# Middle brief"),
    ]:
        sub = archive / d
        sub.mkdir()
        (sub / "00-brief.md").write_text(body, encoding="utf-8")
        (sub / "01-turk-hukuku.md").write_text("category", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", archive)

    result = await mcp_server.get_brief()
    assert result["date"] == "2026-05-06"
    assert "Newer brief" in result["top_brief"]
    assert "01-turk-hukuku.md" in result["category_files"]
    assert result["has_mindmap"] is False


@pytest.mark.asyncio
async def test_get_brief_specific_date(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    sub = archive / "2026-05-05"
    sub.mkdir()
    (sub / "00-brief.md").write_text("# Day brief", encoding="utf-8")
    (sub / "mindmap.html").write_text("<html/>", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", archive)

    result = await mcp_server.get_brief(date="2026-05-05")
    assert result["date"] == "2026-05-05"
    assert result["has_mindmap"] is True


@pytest.mark.asyncio
async def test_get_brief_rejects_invalid_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "2026-05-06").mkdir()
    (archive / "2026-05-06" / "00-brief.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", archive)

    result = await mcp_server.get_brief(date="../etc/passwd")
    assert "error" in result
    assert "invalid date format" in result["error"]


@pytest.mark.asyncio
async def test_get_brief_returns_error_for_missing_date(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "2026-05-06").mkdir()
    (archive / "2026-05-06" / "00-brief.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", archive)

    result = await mcp_server.get_brief(date="2025-01-01")
    assert "error" in result
    assert "no brief found" in result["error"]


# ── get_source_stats ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_source_stats_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    sources = [
        _fake_source(name="A", category="dunya_ai", type="rss", enabled=True),
        _fake_source(name="B", category="dunya_ai", type="reddit", enabled=True),
        _fake_source(name="C", category="legaltech", type="rss", enabled=False),
    ]
    factory = _FakeSessionFactory(
        [
            _FakeResult(scalars=sources),  # SELECT Source
            _FakeResult(scalar_value=120),  # COUNT(Article)
            _FakeResult(scalar_value=42),  # COUNT(embedded)
            _FakeResult(rows=[("dunya_ai", 50), ("legaltech", 10)]),  # 24h by category
        ]
    )
    monkeypatch.setattr(core_stats, "session_factory", factory)

    stats = await mcp_server.get_source_stats()
    assert stats["sources"]["total"] == 3
    assert stats["sources"]["enabled"] == 2
    assert stats["sources"]["disabled"] == 1
    assert stats["sources"]["by_category"]["dunya_ai"] == {"total": 2, "enabled": 2}
    assert stats["sources"]["by_category"]["legaltech"] == {"total": 1, "enabled": 0}
    assert stats["sources"]["by_type"]["rss"] == 2
    assert stats["sources"]["by_type"]["reddit"] == 1
    assert stats["articles"]["total"] == 120
    assert stats["articles"]["embedded"] == 42
    assert stats["articles"]["embedded_pct"] == 35.0
    assert stats["articles"]["fetched_last_24h_by_category"] == {"dunya_ai": 50, "legaltech": 10}


@pytest.mark.asyncio
async def test_get_source_stats_counts_effective_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-disabled sources count toward 'disabled' even if feeds.yaml has them on."""
    sources = [
        _fake_source(name="A", category="dunya_ai", type="rss", enabled=True),
        # User toggled this off via dashboard — counts as disabled even though
        # feeds.yaml still has enabled=True.
        _fake_source(
            name="B", category="dunya_ai", type="rss", enabled=True, is_user_disabled=True
        ),
        _fake_source(name="C", category="legaltech", type="rss", enabled=False),
    ]
    factory = _FakeSessionFactory(
        [
            _FakeResult(scalars=sources),
            _FakeResult(scalar_value=10),
            _FakeResult(scalar_value=5),
            _FakeResult(rows=[]),
        ]
    )
    monkeypatch.setattr(core_stats, "session_factory", factory)

    stats = await mcp_server.get_source_stats()
    assert stats["sources"]["total"] == 3
    assert stats["sources"]["enabled"] == 1  # only A
    assert stats["sources"]["disabled"] == 2  # B (user) + C (feeds)
    assert stats["sources"]["by_category"]["dunya_ai"] == {"total": 2, "enabled": 1}


@pytest.mark.asyncio
async def test_get_source_stats_handles_zero_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    factory = _FakeSessionFactory(
        [
            _FakeResult(scalars=[]),
            _FakeResult(scalar_value=0),
            _FakeResult(scalar_value=0),
            _FakeResult(rows=[]),
        ]
    )
    monkeypatch.setattr(core_stats, "session_factory", factory)

    stats = await mcp_server.get_source_stats()
    assert stats["articles"]["total"] == 0
    assert stats["articles"]["embedded_pct"] == 0.0


# ── search_emsals ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_emsals_handles_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def raises(query: str, *, page_size: int) -> None:
        raise MuhakemeNotConfiguredError("env not set")

    monkeypatch.setattr(mcp_server, "muhakeme_search", raises)
    result = await mcp_server.search_emsals("anayasa", page_size=2)
    assert result["error"] == "muhakeme MCP not configured"
    assert "env not set" in result["detail"]


@pytest.mark.asyncio
async def test_search_emsals_serializes_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    async def search(query: str, *, page_size: int) -> list[EmsalHit]:
        return [
            EmsalHit(
                court="yargitay",
                case_id="2024/123",
                title="Sample case",
                excerpt="Excerpt text",
                url="https://muhakeme.test/x",
                raw={"k": "v"},
            )
        ]

    monkeypatch.setattr(mcp_server, "muhakeme_search", search)
    result = await mcp_server.search_emsals("kişisel veriler", page_size=1)
    assert result["query"] == "kişisel veriler"
    assert len(result["hits"]) == 1
    hit = result["hits"][0]
    assert hit["court"] == "yargitay"
    assert hit["case_id"] == "2024/123"
    assert hit["url"] == "https://muhakeme.test/x"
    # raw payload not leaked to MCP client.
    assert "raw" not in hit


@pytest.mark.asyncio
async def test_search_emsals_rejects_empty_query() -> None:
    result = await mcp_server.search_emsals("   ")
    assert "error" in result


# ── feeds.yaml resource ────────────────────────────────────────────────


def test_feeds_yaml_resource_reads_real_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_yaml = tmp_path / "feeds.yaml"
    fake_yaml.write_text("sources: []\n# rasathane test\n", encoding="utf-8")
    monkeypatch.setattr(mcp_server, "FEEDS_YAML", fake_yaml)

    content = mcp_server.feeds_yaml_resource()
    assert "rasathane test" in content


def test_feeds_yaml_resource_handles_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(mcp_server, "FEEDS_YAML", tmp_path / "ghost.yaml")
    content = mcp_server.feeds_yaml_resource()
    assert "not found" in content


# ── Server contract sanity ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_server_lists_expected_tools_and_resources() -> None:
    tools = await mcp_server.mcp.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "list_sources",
        "recent_articles",
        "search_articles",
        "get_brief",
        "get_source_stats",
        "search_emsals",
    }
    assert expected.issubset(tool_names)

    resources = await mcp_server.mcp.list_resources()
    uris = {str(r.uri) for r in resources}
    assert "rasathane://feeds.yaml" in uris


def test_server_instructions_set() -> None:
    """Defensive: instructions guide Claude Desktop's tool-calling style."""
    assert mcp_server.mcp.instructions is not None
    assert "Türkçe" in mcp_server.mcp.instructions

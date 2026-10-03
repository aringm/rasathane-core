"""Rasathane MCP server — Claude Desktop integration surface.

Design contract:
    - **No LLM calls inside the server.** Tools return raw data; the MCP
      client (Claude Desktop) does the analysis using its own context. This
      is what frees us from the ANTHROPIC_API_KEY dependency the user
      explicitly didn't want.
    - **Per-tool DB session.** Each tool opens its own ``session_factory()``
      session and closes it when done — matches FastAPI's request-scoped
      pattern.
    - **Embedding-only LLM**: ``search_articles`` calls Ollama (local, no
      key) for the query vector. Similarity is then a plain pgvector
      cosine-distance query.
    - **muhakeme proxy**: ``search_emsals`` forwards to the muhakeme.ai MCP
      we already wrote a client for in Phase 7. If the env isn't set, we
      return a structured error rather than crashing the tool call.

Tools are exposed at **module level** rather than inside a ``build_server``
factory — makes them directly importable for tests, and the FastMCP
instance is cheap enough to live as a module global.

Tool bodies are intentionally thin: query + serialization logic lives in
``rasathane_mcp.core``, shared with the FastAPI dashboard so the two
surfaces never disagree on shape or filtering semantics.
"""

from __future__ import annotations

from typing import Any

import structlog
from ingestion.muhakeme_mcp import (
    MuhakemeNotConfiguredError,
)
from ingestion.muhakeme_mcp import (
    search_emsals as muhakeme_search,
)
from mcp.server.fastmcp import FastMCP

from rasathane_mcp.core import articles as core_articles
from rasathane_mcp.core import brief as core_brief
from rasathane_mcp.core import sources as core_sources
from rasathane_mcp.core import stats as core_stats
from rasathane_mcp.core.paths import ARCHIVE_ROOT, FEEDS_YAML, REPO_ROOT
from rasathane_mcp.core.serializers import serialize_article, serialize_source
from rasathane_mcp.dashboard import dashboard_lifespan

log = structlog.get_logger()

# Re-export for backwards compatibility with existing tests that
# ``monkeypatch.setattr(mcp_server, "ARCHIVE_ROOT", ...)``. The Python
# binding semantics make these mutable per-module references.
__all__ = [
    "ARCHIVE_ROOT",
    "FEEDS_YAML",
    "REPO_ROOT",
    "feeds_yaml_resource",
    "get_brief",
    "get_source_stats",
    "list_sources",
    "mcp",
    "muhakeme_search",
    "recent_articles",
    "search_articles",
    "search_emsals",
]

DEFAULT_EMSAL_PAGE_SIZE = 5

mcp = FastMCP(
    "rasathane",
    instructions=(
        "Rasathane is a personal hukuk + AI radar. Use these tools to "
        "discover sources, fetch recent articles by category or type, "
        "do semantic search across embedded content, read archived "
        "daily briefs, and proxy emsal (Turkish legal precedent) "
        "searches to muhakeme.ai. The user's preferred output style is "
        "olgusal modern Türkçe — avoid arkaik or dini-çağrışımlı ifadeler."
    ),
    lifespan=dashboard_lifespan,
)


@mcp.tool()
async def list_sources(
    category: str | None = None,
    type: str | None = None,  # noqa: A002 — matches feeds.yaml field name; user-facing MCP arg
    enabled_only: bool = True,
) -> list[dict[str, Any]]:
    """List configured Rasathane sources.

    Categories: turk_hukuku, dunya_ai, turkiye_ai, legaltech,
    muhakeme_stack. Types: rss, arxiv, reddit. ``enabled_only=True``
    hides feeds that are flagged broken.
    """
    sources = await core_sources.list_sources(
        category=category, type_=type, enabled_only=enabled_only
    )
    log.info(
        "mcp.list_sources",
        category=category,
        type=type,
        enabled_only=enabled_only,
        count=len(sources),
    )
    return [serialize_source(s) for s in sources]


@mcp.tool()
async def recent_articles(
    category: str | None = None,
    type: str | None = None,  # noqa: A002 — matches feeds.yaml field name; user-facing MCP arg
    source_name: str | None = None,
    since_hours: int = core_articles.DEFAULT_RECENT_HOURS,
    limit: int = core_articles.DEFAULT_RECENT_LIMIT,
) -> list[dict[str, Any]]:
    """Articles fetched in the last ``since_hours``, filtered + paged.

    Sort: ``published_at`` DESC (NULLs last), then ``fetched_at`` DESC.
    Use this for "what's new in X category" or "show me posts from
    r/LocalLLaMA today" type queries.
    """
    articles = await core_articles.list_recent(
        category=category,
        type_=type,
        source_name=source_name,
        since_hours=since_hours,
        limit=limit,
    )
    log.info(
        "mcp.recent_articles",
        category=category,
        type=type,
        source_name=source_name,
        since_hours=since_hours,
        count=len(articles),
    )
    return [serialize_article(a) for a in articles]


@mcp.tool()
async def search_articles(
    query: str,
    top_k: int = core_articles.DEFAULT_SEARCH_TOP_K,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search across embedded articles via Ollama qwen3-embedding.

    Only articles with non-NULL embedding vectors are considered. Run
    ``pulse embed`` first if the corpus seems empty. Returns articles
    ordered by cosine similarity (1.0 = identical, ~0 = unrelated).
    """
    rows = await core_articles.semantic_search(query=query, top_k=top_k, category=category)
    log.info(
        "mcp.search_articles",
        query=query[:80],
        top_k=top_k,
        category=category,
        hits=len(rows),
    )
    return [serialize_article(article, similarity=1.0 - dist) for article, dist in rows]


@mcp.tool()
async def get_brief(date: str | None = None) -> dict[str, Any]:
    """Read the stored daily brief for ``date`` (YYYY-MM-DD).

    Without a date, returns the most recent brief in ``archive/``.
    Returns ``{"error": ...}`` if no brief exists yet.
    """
    return core_brief.load_brief(archive_root=ARCHIVE_ROOT, date=date)


@mcp.tool()
async def get_source_stats() -> dict[str, Any]:
    """Snapshot the radar's data state.

    Returns counts by (category, type) for sources, plus 24h article
    ingest counts and embedding coverage. Use this for "is the system
    healthy?" and "what categories have been quiet?" questions.
    """
    return await core_stats.compute_stats()


@mcp.tool()
async def search_emsals(
    query: str,
    page_size: int = DEFAULT_EMSAL_PAGE_SIZE,
) -> dict[str, Any]:
    """Search Turkish legal precedents (proxies to muhakeme.ai MCP).

    Requires ``MUHAKEME_MCP_URL`` (SSE) or ``MUHAKEME_MCP_COMMAND``
    (stdio) in the environment. If neither is set, returns
    ``{"error": "muhakeme MCP not configured"}`` instead of failing.
    """
    if not query.strip():
        return {"error": "query must not be empty"}
    try:
        hits = await muhakeme_search(query, page_size=page_size)
    except MuhakemeNotConfiguredError as e:
        return {"error": "muhakeme MCP not configured", "detail": str(e)}
    return {
        "query": query,
        "hits": [
            {
                "court": h.court,
                "case_id": h.case_id,
                "title": h.title,
                "excerpt": h.excerpt,
                "url": h.url,
            }
            for h in hits
        ],
    }


@mcp.resource("rasathane://feeds.yaml")
def feeds_yaml_resource() -> str:
    """Raw ``data/feeds.yaml`` source catalogue (with verify/disabled notes)."""
    if not FEEDS_YAML.exists():
        return "# feeds.yaml not found\n"
    return FEEDS_YAML.read_text(encoding="utf-8")


# ─── Phase 12-iii: kütüphane tool'ları ──────────────────────────────────


@mcp.tool()
async def list_library_items(
    type: str | None = None,  # noqa: A002 — MCP schema needs unprefixed name
    q: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List user's saved library items (articles + briefs).

    Filter ``type`` to "article" or "brief". Filter ``q`` ILIKE-searches
    note + title + snapshot content. Sorted by ``saved_at DESC``.
    """
    from rasathane_mcp.core import library as core_library

    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200
    return await core_library.list_items(
        item_type=type if type in ("article", "brief") else None,
        q=q,
        offset=0,
        limit=limit,
    )


@mcp.tool()
async def add_to_library(
    article_id: str | None = None,
    brief_date: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Save an article (by id) or a brief (by YYYY-MM-DD) to the library.

    Exactly one of ``article_id`` or ``brief_date`` must be provided.
    Snapshot dondurulur (article DB'den silinse bile içerik kalır).
    Aynı item 2 kere kaydedilirse ``{"error": "already_saved", "id": ...}``
    döner (idempotent guard).
    """
    import uuid as _u
    from datetime import date as _d

    from rasathane_mcp.core import library as core_library

    if (article_id is None) == (brief_date is None):
        return {"error": "exactly one of article_id or brief_date is required"}

    if article_id is not None:
        try:
            aid = _u.UUID(article_id)
        except ValueError:
            return {"error": "invalid article_id (must be UUID)"}
        return await core_library.save_article(article_id=aid, note=note)

    try:
        bdate = _d.fromisoformat(brief_date or "")
    except ValueError:
        return {"error": "invalid brief_date (must be YYYY-MM-DD)"}
    return await core_library.save_brief(brief_date=bdate, note=note, archive_root=ARCHIVE_ROOT)

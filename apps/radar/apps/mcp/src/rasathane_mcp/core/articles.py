"""Article queries — recent feed + semantic search.

Both functions return raw SQLAlchemy rows (or ``(Article, distance)``
tuples for search). Callers do their own serialization so each surface
can attach surface-specific fields (e.g. ``similarity`` for search,
``cursor`` for paginated dashboard lists).

Limits are clamped to the constants defined here so the MCP tools and
the dashboard use exactly the same bounds.

Phase 36-iii: addendum helper'ları (list_recent_titles_by_tags,
list_articles_by_ids, find_related_to_deep_job) eklendi — Ek Analiz tabı
freeform tag context + mukayese kaynak picker beslemesi için.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from llm.embeddings import embed_batch, embed_text
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from store.database import session_factory
from store.models import Article, Source

_log = structlog.get_logger()

DEFAULT_RECENT_HOURS = 24
DEFAULT_RECENT_LIMIT = 50
MAX_RECENT_LIMIT = 200
DEFAULT_SEARCH_TOP_K = 10
MAX_SEARCH_TOP_K = 50


def _clamp_limit(limit: int) -> int:
    if limit < 1:
        return 1
    if limit > MAX_RECENT_LIMIT:
        return MAX_RECENT_LIMIT
    return limit


def _clamp_top_k(top_k: int) -> int:
    if top_k < 1:
        return 1
    if top_k > MAX_SEARCH_TOP_K:
        return MAX_SEARCH_TOP_K
    return top_k


async def list_recent(
    *,
    category: str | None = None,
    type_: str | None = None,
    source_name: str | None = None,
    since_hours: int = DEFAULT_RECENT_HOURS,
    limit: int = DEFAULT_RECENT_LIMIT,
    offset: int = 0,
) -> list[Article]:
    """Articles fetched in the last ``since_hours``, filtered + paged.

    Sort: ``published_at`` DESC (NULLs last), then ``fetched_at`` DESC.
    """
    if since_hours < 1:
        since_hours = 1
    limit = _clamp_limit(limit)
    if offset < 0:
        offset = 0

    since = datetime.now(UTC) - timedelta(hours=since_hours)
    async with session_factory() as session:
        stmt = (
            select(Article)
            .options(selectinload(Article.source))
            .join(Article.source)
            .where(Article.fetched_at >= since)
            .order_by(
                Article.published_at.desc().nulls_last(),
                Article.fetched_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        if category:
            stmt = stmt.where(Source.category == category)
        if type_:
            stmt = stmt.where(Source.type == type_)
        if source_name:
            stmt = stmt.where(Source.name == source_name)
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def semantic_search(
    *,
    query: str,
    top_k: int = DEFAULT_SEARCH_TOP_K,
    category: str | None = None,
) -> list[tuple[Article, float]]:
    """Return ``(article, cosine_distance)`` pairs ordered by similarity.

    Empty/whitespace queries short-circuit before touching Ollama or the
    DB. Callers convert distance → similarity via ``1.0 - distance``.
    """
    if not query.strip():
        return []
    top_k = _clamp_top_k(top_k)

    [query_vec] = await embed_batch([query])
    async with session_factory() as session:
        distance = Article.embedding.cosine_distance(query_vec).label("distance")
        stmt = (
            select(Article, distance)
            .options(selectinload(Article.source))
            .where(Article.embedding.is_not(None))
        )
        if category:
            stmt = stmt.join(Article.source).where(Source.category == category)
        stmt = stmt.order_by(distance).limit(top_k)
        result = await session.execute(stmt)
        return [(article, float(dist)) for article, dist in result.all()]


# ── Phase 36-iii: addendum altyapısı için yardımcılar ────────────────────


async def list_recent_titles_by_tags(
    tags: list[str], days: int = 7, limit: int = 5
) -> list[dict[str, str]]:
    """Son N günde verilen tag'lerdeki (= ``Source.category``) makale başlıkları.

    Tag taxonomy = ``Source.category`` 1-1 (bkz. store.tags). Boş tag listesi
    veya DB hatasında ``[]`` döner (silent-skip — caller addendum üretimini
    durdurmamalı).
    """
    if not tags:
        return []
    if limit < 1:
        return []
    cutoff = datetime.now(UTC) - timedelta(days=max(days, 1))
    try:
        async with session_factory() as session:
            stmt = (
                select(Article.title, Source.name)
                .join(Article.source)
                .where(
                    Article.published_at >= cutoff,
                    Source.category.in_(tags),
                )
                .order_by(Article.published_at.desc().nulls_last())
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.all()
    except Exception as e:
        _log.warning("articles.list_recent_titles_by_tags_failed", error=str(e))
        return []
    return [{"title": title, "source_name": source_name} for title, source_name in rows]


async def list_articles_by_ids(ids: list[Any]) -> list[dict[str, Any]]:
    """ID listesiyle makale detayları (compare addendum için).

    ID'ler UUID string veya UUID objesi olabilir; parse edilemeyen ID atlanır.
    DB hatasında ``[]`` döner.
    """
    if not ids:
        return []
    parsed: list[_uuid.UUID] = []
    for raw in ids:
        if isinstance(raw, _uuid.UUID):
            parsed.append(raw)
            continue
        try:
            parsed.append(_uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    if not parsed:
        return []
    try:
        async with session_factory() as session:
            stmt = (
                select(Article)
                .options(selectinload(Article.source))
                .where(Article.id.in_(parsed))
            )
            result = await session.execute(stmt)
            articles = list(result.scalars().all())
    except Exception as e:
        _log.warning("articles.list_articles_by_ids_failed", error=str(e))
        return []
    out: list[dict[str, Any]] = []
    for a in articles:
        out.append(
            {
                "id": str(a.id),
                "title": a.title,
                "source_name": a.source.name if a.source else "",
                "published_at": a.published_at.isoformat() if a.published_at else "",
                "url": a.url,
                "summary": (a.summary or "")[:500],
            }
        )
    return out


async def find_related_to_deep_job(
    job_id: str, limit: int = 5
) -> list[dict[str, Any]]:
    """Deep job summary embedding'ine en yakın N makale (pgvector cosine).

    summary.md yoksa veya embedding/DB hatasında ``[]`` döner.
    """
    if limit < 1:
        return []
    from rasathane_mcp.core.paths import ARCHIVE_ROOT

    summary_path = ARCHIVE_ROOT / "deep" / job_id / "summary.md"
    if not summary_path.is_file():
        return []
    try:
        summary_text = summary_path.read_text(encoding="utf-8")[:2000]
    except OSError as e:
        _log.warning("articles.find_related_summary_read_failed", error=str(e))
        return []
    if not summary_text.strip():
        return []
    try:
        vec = await embed_text(summary_text)
    except Exception as e:
        _log.warning("articles.find_related_embed_failed", error=str(e))
        return []
    try:
        async with session_factory() as session:
            distance = Article.embedding.cosine_distance(vec).label("distance")
            stmt = (
                select(Article, distance)
                .options(selectinload(Article.source))
                .where(Article.embedding.is_not(None))
                .order_by(distance)
                .limit(limit)
            )
            result = await session.execute(stmt)
            pairs = result.all()
    except Exception as e:
        _log.warning("articles.find_related_query_failed", error=str(e))
        return []
    out: list[dict[str, Any]] = []
    for article, _dist in pairs:
        out.append(
            {
                "id": str(article.id),
                "title": article.title,
                "source_name": article.source.name if article.source else "",
                "published_at": article.published_at.isoformat()
                if article.published_at
                else "",
                "url": article.url,
                "summary": (article.summary or "")[:400],
            }
        )
    return out

"""DTO-style dict serializers for SQLAlchemy rows.

The MCP tools return these dicts directly to Claude Desktop; the
dashboard JSON endpoints return them as the response body. Keeping a
single shape per entity guarantees the two surfaces never disagree.
"""

from __future__ import annotations

from typing import Any

from store.models import Article, Source

from rasathane_mcp.core.text_normalize import normalize_title_tr


def serialize_source(s: Source) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "name": s.name,
        "category": s.category,
        "type": s.type,
        "url": s.url,
        "enabled": s.enabled,
        "is_user_disabled": s.is_user_disabled,
        # Pre-computed convenience flag — clients don't need to know the
        # AND semantics. Stays in lockstep with list_enabled_sources.
        "effective_enabled": s.enabled and not s.is_user_disabled,
        "fetch_interval_minutes": s.fetch_interval_minutes,
        "last_fetched_at": s.last_fetched_at.isoformat() if s.last_fetched_at else None,
        "metadata": s.metadata_,
    }


def serialize_article(
    a: Article,
    *,
    similarity: float | None = None,
    in_library: bool | None = None,
    library_item_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(a.id),
        "url": a.url,
        "title": a.title,
        # Phase 15-iii: ALL CAPS başlıklar UI'da göze battığı için
        # normalize edilmiş bir gösterim kopyası eklendi. Original title
        # DB-side search/embedding için ham kalır.
        "title_display": normalize_title_tr(a.title) if a.title else a.title,
        "summary": a.summary,
        "summary_tr_short": a.summary_tr_short,
        "summary_tr_long": a.summary_tr_long,
        "author": a.author,
        "published_at": a.published_at.isoformat() if a.published_at else None,
        "fetched_at": a.fetched_at.isoformat(),
        "metadata": a.metadata_,
        "source": {
            "name": a.source.name,
            "category": a.source.category,
            "type": a.source.type,
        },
    }
    if similarity is not None:
        payload["similarity"] = similarity
    if in_library is not None:
        payload["in_library"] = in_library
        payload["library_item_id"] = library_item_id
    return payload

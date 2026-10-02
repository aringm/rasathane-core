"""Aggregate health snapshot — source counts, embed coverage, 24h ingest."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from store.database import session_factory
from store.models import Article, Source


async def compute_stats() -> dict[str, Any]:
    """Snapshot the radar's data state.

    Used by the MCP ``get_source_stats`` tool and the dashboard top bar.
    The 24h window matches the dashboard's default feed window so the
    "last 24h" numbers in both surfaces tell the same story.
    """
    since = datetime.now(UTC) - timedelta(hours=24)
    async with session_factory() as session:
        sources = list((await session.execute(select(Source))).scalars().all())
        total_articles = (
            await session.execute(select(func.count()).select_from(Article))
        ).scalar_one()
        embedded_count = (
            await session.execute(
                select(func.count()).select_from(Article).where(Article.embedding.is_not(None))
            )
        ).scalar_one()
        recent_by_cat_stmt = (
            select(Source.category, func.count(Article.id))
            .join(Article.source)
            .where(Article.fetched_at >= since)
            .group_by(Source.category)
        )
        recent_by_cat = dict((await session.execute(recent_by_cat_stmt)).all())

    sources_by_category: dict[str, dict[str, int]] = {}
    sources_by_type: dict[str, int] = {}
    enabled = 0
    user_silenced = 0
    yaml_disabled = 0
    for s in sources:
        cat_bucket = sources_by_category.setdefault(s.category, {"total": 0, "enabled": 0})
        cat_bucket["total"] += 1
        # Match list_enabled_sources semantics — effective state, not the raw
        # feeds.yaml flag — so the "enabled" count never disagrees with what
        # the workers actually fetch.
        if s.enabled and not s.is_user_disabled:
            cat_bucket["enabled"] += 1
            enabled += 1
        # Phase 15-i: 2 ayrı kapalı sayım — UI'ya doğru etiket için
        # ("susturulmuş" sadece is_user_disabled=true; yaml_disabled
        # ise feeds.yaml'da enabled: false olanlar).
        if s.is_user_disabled:
            user_silenced += 1
        if not s.enabled:
            yaml_disabled += 1
        sources_by_type[s.type] = sources_by_type.get(s.type, 0) + 1

    return {
        "sources": {
            "total": len(sources),
            "enabled": enabled,
            "disabled": len(sources) - enabled,
            "user_silenced": user_silenced,
            "yaml_disabled": yaml_disabled,
            "by_category": sources_by_category,
            "by_type": sources_by_type,
        },
        "articles": {
            "total": int(total_articles),
            "embedded": int(embedded_count),
            "embedded_pct": (
                round(100.0 * embedded_count / total_articles, 1) if total_articles else 0.0
            ),
            "fetched_last_24h_by_category": {k: int(v) for k, v in recent_by_cat.items()},
        },
    }

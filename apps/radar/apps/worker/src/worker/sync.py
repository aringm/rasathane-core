"""Sync orchestration: enumerate enabled sources, run per-source sync, commit."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog
from ingestion.github_releases import fetch_github_releases
from ingestion.github_trending import fetch_trending_feeds
from ingestion.huggingface_models import fetch_hf_models
from ingestion.medium_rss import fetch_medium_feeds
from ingestion.nitter import NitterUnavailableError, fetch_recent_tweets

# Phase 35-xxiii: Reddit OAuth devre dışı — kullanıcı Developer App setup
# adımından vazgeçti. Adapter + testler korunur (`packages/ingestion/
# reddit_rss.py`); ileride REDDIT_CLIENT_ID/SECRET/USER_AGENT env'e
# eklendiğinde aşağıdaki çağrıyı uncomment ile aktive edilebilir.
# from ingestion.reddit_rss import fetch_reddit_feeds
from ingestion.sync import sync_one_source
from rasathane_mcp.core.paths import ARCHIVE_ROOT
from rasathane_mcp.core.social_watch import load_social_watch
from sqlalchemy.ext.asyncio import AsyncSession
from store.repository import list_enabled_sources

# Re-export so existing callers (CLI, tests) that imported ``sync_one_source``
# from ``worker.sync`` keep working without churn.
__all__ = ["sync_all_enabled", "sync_one_source", "sync_social_watch_releases"]

log = structlog.get_logger()


async def sync_all_enabled(session: AsyncSession) -> dict[str, int]:
    """Fetch all enabled sources.

    Returns ``{source_name: inserted_count}`` (or ``-1`` for failures).
    Per-source errors use a SAVEPOINT so one bad feed doesn't poison the
    transaction for the rest. Commits at the end.
    """
    sources = await list_enabled_sources(session)
    results: dict[str, int] = {}
    for source in sources:
        try:
            async with session.begin_nested():
                inserted = await sync_one_source(session, source)
            results[source.name] = inserted
            log.info("sync.source.ok", source=source.name, inserted=inserted)
        except Exception as e:
            log.error(
                "sync.source.failed",
                source=source.name,
                url=source.url,
                error=str(e),
                error_type=type(e).__name__,
            )
            results[source.name] = -1
    await session.commit()

    # Phase 33-ii: GitHub releases + HuggingFace model release sync.
    # Bu adımlar DB'ye yazmaz — cache dosyalarına yazar (dashboard cache-first
    # okur). Hata olursa orchestration kırılmaz, log'a düşer.
    try:
        await sync_social_watch_releases()
    except Exception as e:
        log.error(
            "sync.social_watch.failed",
            error=str(e),
            error_type=type(e).__name__,
        )
    return results


async def sync_social_watch_releases() -> None:
    """social_watch.yaml içindeki github + huggingface handle'larını cache'le.

    Phase 33-ii: cache `archive/social_watch_cache/` altına yazılır.
    ``/api/social-watch/feed`` bu dosyaları okur. Cron sync responsible.
    """
    watch = load_social_watch()
    gh_handles = [p.handle for p in watch.people if p.enabled and p.platform == "github"]
    hf_authors = [p.handle for p in watch.people if p.enabled and p.platform == "huggingface"]
    cache_root = ARCHIVE_ROOT / "social_watch_cache"

    log.info("sync.github.start", count=len(gh_handles))
    gh_posts = await fetch_github_releases(gh_handles, cache_root=cache_root)
    log.info("sync.github.done", posts=len(gh_posts))

    log.info("sync.hf.start", count=len(hf_authors))
    hf_posts = await fetch_hf_models(hf_authors, cache_root=cache_root)
    log.info("sync.hf.done", posts=len(hf_posts))

    # Phase 35-xvi: Reddit RSS feed sync. Phase 35-xxi'de OAuth flow'a
    # taşındı; Phase 35-xxiii'de kullanıcı Developer App setup'tan
    # vazgeçtiği için worker sync'ten çıkarıldı.
    # Aktivasyon: yukarıda `from ingestion.reddit_rss import ...` ve aşağıyı
    # uncomment + `.env`'e REDDIT_CLIENT_ID/SECRET/USER_AGENT ekle.
    # log.info("sync.reddit.start")
    # reddit_posts = await fetch_reddit_feeds(cache_root=cache_root)
    # log.info("sync.reddit.done", posts=len(reddit_posts))

    # Phase 35-xvii: Medium RSS feed sync. DEFAULT_PUBLICATIONS curated:
    # Towards Data Science + Better Programming. Medium dışı blog'lar
    # (HuggingFace, OpenAI) için gelecekte ayrı `tech_blog_rss.py` adapter.
    log.info("sync.medium.start")
    medium_posts = await fetch_medium_feeds(cache_root=cache_root)
    log.info("sync.medium.done", posts=len(medium_posts))

    # Phase 35-xviii: GitHub trending discovery. Sabit watch list yerine
    # search API ile topic + stars + pushed filter — son hafta aktif
    # trending repo'lar. DEFAULT_QUERIES: llm + ai-agents + open-source-llm
    # + legaltech + turkish-nlp. github_releases.py sabit watch list ile
    # paralel — ikisi de aynı cache_root'a yazar, feed endpoint birleştirir.
    log.info("sync.github_trending.start")
    trending_posts = await fetch_trending_feeds(cache_root=cache_root)
    log.info("sync.github_trending.done", posts=len(trending_posts))

    # Phase 35-xxii: Nitter X handle refresh. social_watch.yaml'dan
    # `platform: x` + enabled handle'lar için Nitter scraper çağır.
    # Phase 32-i lazy-on-demand modeli (sadece dashboard tool isteğinde)
    # karpathy.json gibi cache'leri stale bırakıyordu; cron sync'e ekleme
    # otomatik refresh sağlar. Nitter instance fail-soft (warning + skip).
    x_handles = [
        p.handle.lstrip("@")
        for p in watch.people
        if p.enabled and p.platform == "x"
    ]
    log.info("sync.nitter.start", count=len(x_handles))
    nitter_total = 0
    nitter_ok = 0
    for handle in x_handles:
        try:
            posts = await fetch_recent_tweets(handle, limit=10)
        except NitterUnavailableError as e:
            log.warning("sync.nitter.handle_unavailable", handle=handle, err=str(e)[:120])
            continue
        except Exception as e:
            log.warning("sync.nitter.handle_failed", handle=handle, err=str(e)[:120])
            continue
        # Cache: <handle>.json — Phase 32-i pattern, endpoint normalize
        # (Phase 35-xix) eski `published_at` schema'sını UI'da düzgün gösterir.
        cache_path = cache_root / f"{handle}.json"
        try:
            cache_path.write_text(
                json.dumps(
                    {
                        "fetched_at": datetime.now(UTC).isoformat(),
                        "source": "nitter",
                        "handle": handle,
                        "posts": posts,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            nitter_ok += 1
            nitter_total += len(posts)
        except OSError as e:
            log.warning("sync.nitter.cache_write_failed", handle=handle, err=str(e)[:120])
    log.info("sync.nitter.done", handles_ok=nitter_ok, total_posts=nitter_total)

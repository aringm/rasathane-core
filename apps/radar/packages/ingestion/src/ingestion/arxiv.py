"""ArXiv Atom API ingester.

Why a dedicated ingester (and not just another RSS row in feeds.yaml):

    1. **Abstract**: ArXiv's RSS feeds (``/rss/cs.AI``) only carry the title;
       the Atom API (``/api/query?search_query=cat:cs.AI``) returns the full
       abstract — clustering and emsal-injection care about abstract text.
    2. **Multi-category**: a single paper has one ``primary_category`` plus
       up to a dozen ``category`` siblings. We surface both so a cs.CL paper
       cross-listed under cs.AI ends up in the right cluster.
    3. **Stable ID**: ArXiv IDs are immutable across versions
       (``2401.12345v1`` → ``2401.12345v2``); we strip the version suffix to
       deduplicate updates.
    4. **PDF link**: callers (future YouTube-style deep-dive flow) will want
       direct PDF access without re-querying.

Per ArXiv ToS the API asks callers to wait 3 seconds between requests; pass
a ``RateLimiter`` configured with ``max_calls=1, window_seconds=3.0`` and
the ingester acquires before every fetch. Without one it falls through (no
delay) — fine for tests but not production.

Source URL format (stored verbatim in feeds.yaml)::

    http://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending&max_results=20
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx
import structlog

from ingestion.base import BaseIngester, IngestedArticle

log = structlog.get_logger()

USER_AGENT = "rasathane/0.1 (+https://github.com/aringm/rasathane)"
HTTP_TIMEOUT = httpx.Timeout(30.0)
SUMMARY_MAX_WORDS = 200
RATE_LIMIT_KEY = "arxiv"

_WHITESPACE_RE = re.compile(r"\s+")
# Matches modern ``2401.12345`` (with optional v3 suffix) or legacy
# ``cs.CL/0102015`` style identifiers.
_ARXIV_ID_RE = re.compile(r"(?:abs|pdf)/((?:[a-zA-Z\-\.]+/)?\d{4,7}\.?\d{0,5})(?:v\d+)?")


def _normalize(text: str | None) -> str | None:
    if not text:
        return None
    collapsed = _WHITESPACE_RE.sub(" ", text).strip()
    return collapsed or None


def _cap_words(text: str | None, n: int) -> str | None:
    if not text:
        return None
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "…"


def _to_datetime(struct_time: Any) -> datetime | None:
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _extract_arxiv_id(url: str) -> str | None:
    """Pull the bare ID (no version) out of an arxiv abs/pdf URL."""
    if not url:
        return None
    match = _ARXIV_ID_RE.search(url)
    return match.group(1) if match else None


def _join_authors(entry: Any) -> str | None:
    """ArXiv lists authors as ``entry.authors``; fall back to ``entry.author``."""
    authors_attr = entry.get("authors")
    if isinstance(authors_attr, list) and authors_attr:
        names = [a.get("name") for a in authors_attr if isinstance(a, dict) and a.get("name")]
        if names:
            return ", ".join(names)
    return _normalize(entry.get("author"))


def _categories(entry: Any) -> tuple[str | None, list[str]]:
    """Return ``(primary, all_categories)`` from an arxiv entry.

    feedparser exposes ``arxiv_primary_category`` as a dict and ``tags`` as
    the list of ``<category>`` siblings.
    """
    primary_raw = entry.get("arxiv_primary_category") or {}
    primary = primary_raw.get("term") if isinstance(primary_raw, dict) else None

    tags = entry.get("tags") or []
    all_terms: list[str] = []
    for tag in tags:
        if isinstance(tag, dict) and tag.get("term"):
            all_terms.append(tag["term"])
    return primary, all_terms


def _pdf_url(entry: Any) -> str | None:
    """ArXiv entries carry an alternate-html link AND a PDF ``related`` link."""
    links = entry.get("links") or []
    for link in links:
        if not isinstance(link, dict):
            continue
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            href = link.get("href")
            if href:
                return str(href)
    return None


class ArxivIngester(BaseIngester):
    """Atom-API powered ingester for arxiv.org.

    Parsing is delegated to feedparser (sync, run via ``asyncio.to_thread``);
    we add arxiv-specific metadata enrichment on top.
    """

    type_name = "arxiv"

    async def fetch(
        self,
        source_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestedArticle]:
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(RATE_LIMIT_KEY)

        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = await client.get(source_url)
            response.raise_for_status()
            body = response.content

        parsed = await asyncio.to_thread(feedparser.parse, body)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(
                f"feedparser failed to parse ArXiv response from {source_url}: "
                f"{parsed.bozo_exception!r}"
            )

        articles: list[IngestedArticle] = []
        for entry in parsed.entries:
            url = entry.get("link") or entry.get("id")
            if not url:
                log.warning("arxiv.skip_no_url", source=source_url, entry_id=entry.get("id"))
                continue

            title = _normalize(entry.get("title")) or "(başlıksız)"
            summary = _cap_words(_normalize(entry.get("summary")), SUMMARY_MAX_WORDS)
            author = _join_authors(entry)
            published_at = _to_datetime(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )
            arxiv_id = _extract_arxiv_id(url)
            primary_category, categories = _categories(entry)

            entry_meta: dict[str, Any] = {
                "feed_url": source_url,
                "source_kind": "arxiv",
            }
            if arxiv_id:
                entry_meta["arxiv_id"] = arxiv_id
            if primary_category:
                entry_meta["arxiv_primary_category"] = primary_category
            if categories:
                entry_meta["arxiv_categories"] = categories
            pdf = _pdf_url(entry)
            if pdf:
                entry_meta["pdf_url"] = pdf
            if metadata:
                entry_meta.update(metadata)

            articles.append(
                IngestedArticle(
                    url=url,
                    url_hash=IngestedArticle.hash_url(url),
                    title=title[:1024],
                    summary=summary,
                    author=author[:255] if author else None,
                    published_at=published_at,
                    metadata=entry_meta,
                )
            )

        log.info("arxiv.fetched", source=source_url, count=len(articles))
        return articles

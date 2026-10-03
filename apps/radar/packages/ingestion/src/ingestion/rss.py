"""RSS / Atom feed ingester (httpx async fetch + feedparser thread-offload)."""

from __future__ import annotations

import asyncio
import html
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

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(text: str | None) -> str | None:
    """Strip HTML tags, decode entities, collapse whitespace."""
    if not text:
        return None
    no_tags = _HTML_TAG_RE.sub(" ", text)
    decoded = html.unescape(no_tags)
    return _WHITESPACE_RE.sub(" ", decoded).strip() or None


def _cap_words(text: str | None, n: int) -> str | None:
    """Cap a string to its first n words, append ellipsis if truncated."""
    if not text:
        return None
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "…"


def _to_datetime(struct_time: Any) -> datetime | None:
    """Convert feedparser's time.struct_time to UTC datetime."""
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


class RssIngester(BaseIngester):
    """RSS / Atom ingester.

    Network fetch via ``httpx.AsyncClient`` (consistent timeouts/retries),
    parsing via ``feedparser`` inside ``asyncio.to_thread`` (feedparser is
    sync C). Per-item errors are logged + skipped; only catastrophic feed
    errors (HTTP failure, no entries at all) raise.
    """

    type_name = "rss"

    async def fetch(
        self,
        source_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestedArticle]:
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
                f"feedparser failed to parse {source_url}: {parsed.bozo_exception!r}"
            )

        articles: list[IngestedArticle] = []
        for entry in parsed.entries:
            url = entry.get("link") or entry.get("id")
            if not url:
                log.warning("rss.skip_no_url", source=source_url, entry_id=entry.get("id"))
                continue

            title = _clean_text(entry.get("title")) or "(başlıksız)"

            raw_summary = entry.get("summary") or entry.get("description")
            if not raw_summary and entry.get("content"):
                raw_summary = entry["content"][0].get("value") if entry["content"] else None
            summary = _cap_words(_clean_text(raw_summary), SUMMARY_MAX_WORDS)

            author = _clean_text(entry.get("author"))
            published_at = _to_datetime(
                entry.get("published_parsed") or entry.get("updated_parsed")
            )

            articles.append(
                IngestedArticle(
                    url=url,
                    url_hash=IngestedArticle.hash_url(url),
                    title=title[:1024],
                    summary=summary,
                    author=author[:255] if author else None,
                    published_at=published_at,
                    metadata={"feed_url": source_url, **(metadata or {})},
                )
            )

        log.info("rss.fetched", source=source_url, count=len(articles))
        return articles

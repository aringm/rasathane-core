"""Reddit ingester (anonymous public JSON API, no auth required).

Why no PRAW: Reddit's read-only JSON endpoints (``/r/<sub>/<sort>.json``)
work without OAuth as long as we send a unique User-Agent and stay under
60 requests/minute (per Reddit's API rules). PRAW would buy us 600 req/min
and richer comment access, but for our use case (5-10 subreddits, hourly
fetch ≈ 600 requests/day across all of them) the anon limit is plenty.

Trade-offs:
    - **Anon rate limit (60/min)**: enforced via the shared
      ``RateLimiter`` Phase 8A primitive. Pass one in via the registry —
      without it, the ingester fetches at full httpx speed, which Reddit
      will throttle.
    - **No comment ingestion**: we only consume submissions. Comment-mining
      is heavier and noisier; defer to Phase 9+ if it ever proves useful.
    - **Permalink as the canonical URL**: even for linkposts whose ``url``
      points to an external site, we use ``reddit.com<permalink>`` so that
      url_hash de-dupes the *Reddit conversation*, not the underlying link.
      The external URL is preserved in metadata.
    - **selftext can be empty** for linkposts. We render a short marker so
      ``IngestedArticle.summary`` is never an empty string masquerading as
      content.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from ingestion.base import BaseIngester, IngestedArticle

log = structlog.get_logger()

# Reddit asks for a UA in this shape: <platform>:<app id>:<version> (by /u/<user>).
USER_AGENT = "linux:rasathane:0.1 (by /u/aringm)"
HTTP_TIMEOUT = httpx.Timeout(30.0)
SUMMARY_MAX_WORDS = 200
RATE_LIMIT_KEY = "reddit"
LINKPOST_PLACEHOLDER = "[Link post — see external_url in metadata]"


def _to_datetime(unix_ts: float | int | None) -> datetime | None:
    if unix_ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(unix_ts), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _cap_words(text: str | None, n: int) -> str | None:
    if not text:
        return None
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "…"


def _normalize_author(value: Any) -> str | None:
    """Reddit's ``author`` is "[deleted]" for removed users; preserve as-is
    but trim oddities like None or empty strings."""
    if not value:
        return None
    text = str(value).strip()
    return text or None


class RedditIngester(BaseIngester):
    """JSON-API ingester for ``reddit.com``.

    Source URL format expected in feeds.yaml::

        https://www.reddit.com/r/<subreddit>/new.json?limit=25
        https://www.reddit.com/r/<subreddit>/hot.json?limit=25
    """

    type_name = "reddit"

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
            payload = response.json()

        children = payload.get("data", {}).get("children", [])
        if not isinstance(children, list):
            raise RuntimeError(
                f"Reddit JSON shape unexpected from {source_url}: data.children is not a list"
            )

        articles: list[IngestedArticle] = []
        for child in children:
            if not isinstance(child, dict) or child.get("kind") != "t3":
                # t3 = link post; t1=comment, t5=subreddit etc — we skip those.
                continue
            d = child.get("data") or {}
            if not isinstance(d, dict):
                continue

            permalink = d.get("permalink")
            if not permalink:
                log.warning(
                    "reddit.skip_no_permalink",
                    source=source_url,
                    reddit_id=d.get("id"),
                )
                continue
            article_url = "https://www.reddit.com" + permalink

            title_raw = d.get("title")
            title = (str(title_raw).strip() if title_raw else None) or "(başlıksız)"

            selftext = (d.get("selftext") or "").strip()
            summary = _cap_words(selftext, SUMMARY_MAX_WORDS) if selftext else LINKPOST_PLACEHOLDER

            author = _normalize_author(d.get("author"))
            published_at = _to_datetime(d.get("created_utc"))

            entry_meta: dict[str, Any] = {
                "feed_url": source_url,
                "source_kind": "reddit",
                "subreddit": d.get("subreddit"),
                "score": d.get("score"),
                "num_comments": d.get("num_comments"),
                "is_self": bool(d.get("is_self")),
                "reddit_id": d.get("id"),
            }
            flair = d.get("link_flair_text")
            if flair:
                entry_meta["flair"] = flair
            external = d.get("url")
            if external and not bool(d.get("is_self")):
                entry_meta["external_url"] = external
            if metadata:
                entry_meta.update(metadata)

            articles.append(
                IngestedArticle(
                    url=article_url,
                    url_hash=IngestedArticle.hash_url(article_url),
                    title=title[:1024],
                    summary=summary,
                    author=author[:255] if author else None,
                    published_at=published_at,
                    metadata=entry_meta,
                )
            )

        log.info("reddit.fetched", source=source_url, count=len(articles))
        return articles

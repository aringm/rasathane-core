"""Ingester registry — type string → ingester instance.

Phase 8A added the ``rate_limiter`` slot so adapters that need a budgeted
client (ArXiv: 1 req/3s) can share a single Redis-backed limiter across the
process. Adapters that don't need one ignore the kwarg.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ingestion.arxiv import ArxivIngester
from ingestion.base import BaseIngester
from ingestion.reddit import RedditIngester
from ingestion.resmi_gazete import ResmiGazeteIngester
from ingestion.rss import RssIngester
from ingestion.youtube_channel import YoutubeChannelIngester

if TYPE_CHECKING:
    from ingestion.rate_limit import RateLimiter

INGESTER_REGISTRY: dict[str, type[BaseIngester]] = {
    RssIngester.type_name: RssIngester,
    ArxivIngester.type_name: ArxivIngester,
    RedditIngester.type_name: RedditIngester,
    YoutubeChannelIngester.type_name: YoutubeChannelIngester,
    ResmiGazeteIngester.type_name: ResmiGazeteIngester,
}


def get_ingester(
    type_name: str,
    *,
    rate_limiter: RateLimiter | None = None,
) -> BaseIngester:
    """Look up + instantiate an ingester by its registered type name.

    Raises ``ValueError`` if no ingester is registered for the type.
    """
    cls = INGESTER_REGISTRY.get(type_name)
    if cls is None:
        raise ValueError(
            f"No ingester registered for type {type_name!r}. "
            f"Registered: {sorted(INGESTER_REGISTRY)}"
        )
    return cls(rate_limiter=rate_limiter)

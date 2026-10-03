"""Ingester base class and DTO.

Contract: ingesters return Pydantic-validated DTOs without touching the
database. A separate persister (``store.repository.upsert_articles``)
handles deduplication and persistence. Unit tests for ingesters need no DB.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ingestion.rate_limit import RateLimiter


class IngestedArticle(BaseModel):
    """An article fetched from a source, validated but not yet persisted.

    ``url_hash`` is computed once at construction; the persister uses it
    for ON CONFLICT deduplication. Summaries MUST already be capped at
    ~200 words by the ingester (FSEK iktibas sınırı).
    """

    model_config = ConfigDict(frozen=True)

    url: str
    url_hash: str
    title: str
    summary: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def hash_url(url: str) -> str:
        """Canonical sha256 hex digest of a URL — primary dedupe key.

        Strips whitespace and lowercases. Keeps query string intact (some
        sites use query params for IDs).
        """
        normalized = url.strip().lower()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class BaseIngester(ABC):
    """Abstract base for all source ingesters.

    Implementations must:
      - Be **DB-agnostic**: no SQLAlchemy / DB awareness.
      - Be **async**: use httpx.AsyncClient or thread-offloaded sync libs.
      - Be **resilient**: catch + log per-item errors; keep going on partial
        feeds. Surface only fatal errors (network down, parse impossible).
      - **Cap summaries at ~200 words** before yielding.

    The optional ``rate_limiter`` slot lets the registry inject a shared
    Redis-backed limiter (used by ArXiv etc.); ingesters that don't need
    one simply ignore it.
    """

    type_name: str  # registry key, e.g. "rss"

    def __init__(self, *, rate_limiter: RateLimiter | None = None) -> None:
        self._rate_limiter = rate_limiter

    @abstractmethod
    async def fetch(
        self,
        source_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestedArticle]:
        """Return all articles available from ``source_url`` right now."""
        raise NotImplementedError

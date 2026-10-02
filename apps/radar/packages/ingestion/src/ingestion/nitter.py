"""Nitter scraper — X (Twitter) son paylaşımlarını çekme.

Phase 32-i.3: social_watch modal'ında "Son tweet'ler" sekmesi için lazy/JIT
fetch katmanı. Mevcut RSS ingester ana akışa girer; bu modül *ana akışa
girmeden* tek bir kişinin paylaşımlarını döndürür.

Mimari kararlar:
  - **RSS-first**: Nitter instance'larının `/{handle}/rss` endpoint'i
    feedparser ile parse edilebilir. HTML scrape'e göre çok daha stabil.
  - **Multi-instance fallback**: Tek bir instance fail ederse bir sonrakini
    dene. Nitter ekosistemi kırılgan; instance'lar zaman zaman düşer.
  - **No ingester registry kaydı**: Bu fetcher main pipeline'a girmez.
    ``social_posts.py`` ile cache + endpoint katmanından kullanılır.
  - **Defense-in-depth**: Dönen metinler ``social_watch.is_safe_for_llm``
    ile pre-filter edilir (kullanım anında çağırırlar; bu modül sadece
    fetch yapar).

Default instance listesi env override edilebilir: ``NITTER_INSTANCES``
(virgülle ayrılmış host listesi). Boşsa hardcoded fallback set kullanılır.
"""

from __future__ import annotations

import asyncio
import html
import os
import re
from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx
import structlog

log = structlog.get_logger()

USER_AGENT = "rasathane/0.1 (+https://github.com/aringm/rasathane; social_watch viewer)"
HTTP_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

# Bilinen Nitter instance'ları (2026 ortası itibarıyla aktif olabilenler).
# Aksi tahmin edilemez; runtime'da çoğu birden çökebilir. Multi-fallback
# zorunlu. Env override: ``NITTER_INSTANCES=https://a.example,https://b.example``
_DEFAULT_NITTER_INSTANCES = (
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.net",
    "https://nitter.it",
    "https://nitter.unixfox.eu",
)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class NitterUnavailableError(RuntimeError):
    """Tüm Nitter instance'ları fail etti; canlı veri çekilemedi.

    Caller stale cache fallback yapabilir.
    """


def _get_instances() -> tuple[str, ...]:
    """Lazy env read — test'ler monkeypatch yapabilsin diye her çağrıda okur."""
    raw = os.environ.get("NITTER_INSTANCES", "").strip()
    if not raw:
        return _DEFAULT_NITTER_INSTANCES
    items = tuple(s.strip() for s in raw.split(",") if s.strip())
    return items or _DEFAULT_NITTER_INSTANCES


def _normalize_handle(handle: str) -> str:
    """`@karpathy` → `karpathy`; URL-safe form.

    Önce whitespace strip et, sonra `@` prefix'ini at — sıra önemli çünkü
    `"  @karpathy  "` girdisinde lstrip("@") whitespace yüzünden hiçbir
    şey yapmaz.
    """
    return handle.strip().lstrip("@")


def _clean_text(text: str | None) -> str:
    """RSS summary HTML tag temizleme + entity decode + whitespace collapse."""
    if not text:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    decoded = html.unescape(no_tags)
    return _WHITESPACE_RE.sub(" ", decoded).strip()


def _to_datetime(struct_time: Any) -> datetime | None:
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _parse_rss(body: bytes, *, limit: int) -> list[dict[str, Any]]:
    """feedparser ile parse + ilk N item'ı normalize et."""
    parsed = feedparser.parse(body)
    items: list[dict[str, Any]] = []
    for entry in parsed.entries[:limit]:
        text = _clean_text(entry.get("title") or entry.get("summary"))
        if not text:
            continue
        items.append(
            {
                "id": str(entry.get("id") or entry.get("link") or ""),
                "url": entry.get("link") or "",
                "text": text,
                "author": _clean_text(entry.get("author")),
                "published_at": (
                    _to_datetime(entry.get("published_parsed") or entry.get("updated_parsed"))
                ),
            }
        )
    # ISO-format her published_at — JSON serialize için
    for it in items:
        if isinstance(it["published_at"], datetime):
            it["published_at"] = it["published_at"].isoformat()
    return items


async def _try_instance(
    client: httpx.AsyncClient, instance: str, handle: str, limit: int
) -> list[dict[str, Any]]:
    """Tek bir Nitter instance'ından RSS fetch + parse."""
    url = f"{instance.rstrip('/')}/{handle}/rss"
    r = await client.get(url)
    r.raise_for_status()
    items = await asyncio.to_thread(_parse_rss, r.content, limit=limit)
    return items


async def fetch_recent_tweets(handle: str, *, limit: int = 10) -> list[dict[str, Any]]:
    """X (Twitter) son N paylaşımı Nitter üzerinden al.

    Returns: ``[{"id", "url", "text", "author", "published_at"}, ...]``

    Raises: ``NitterUnavailableError`` tüm instance'lar fail ederse.

    Ham metin döner — caller ``social_watch.is_safe_for_llm`` ile
    injection filter uygulamalı.
    """
    handle = _normalize_handle(handle)
    if not handle:
        return []
    instances = _get_instances()
    last_error: Exception | None = None
    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        for instance in instances:
            try:
                items = await _try_instance(client, instance, handle, limit)
                log.info(
                    "nitter.ok",
                    instance=instance,
                    handle=handle,
                    count=len(items),
                )
                return items
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.ReadError,
                httpx.HTTPStatusError,
                httpx.HTTPError,
                OSError,
            ) as e:
                last_error = e
                log.warning(
                    "nitter.instance_failed",
                    instance=instance,
                    handle=handle,
                    error=type(e).__name__,
                    detail=str(e)[:120],
                )
                continue
    raise NitterUnavailableError(
        f"All {len(instances)} Nitter instances failed for @{handle}: "
        f"{type(last_error).__name__ if last_error else 'no_attempts'}"
    )

"""Medium RSS adapter — Phase 35-xvii.

Endpoint: ``https://medium.com/feed/{publication-or-user}``
Anon erişim, sınırsız (auth yok). RSS 2.0 format (Reddit Atom 1.0'tan
farklı). `<pubDate>` RFC 822 datetime → `email.utils.parsedate_to_datetime`
ile ISO 8601'e çevrilir (Phase 35-xv time filter lexicographic compare
gereği).

Mimari kuralı: LLM çağrısı yok — yalnız RSS parse + cache I/O.

Publication → tags mapping (kullanıcı ilgi alanlarına göre curated):
    towards-data-science  → ["dunya_ai"]            (AI/DS general)
    better-programming    → ["dunya_ai"]            (programming + AI)
    @theaccountabilist    → ["dunya_ai"]            (NLP/LLM yazar)

Topic feed'leri Medium'da deprecated; sadece publication ve user feed'ler.
HuggingFace Blog, OpenAI Engineering vb. Medium dışı blog'lar
**bu adapter kapsamında değil** — gelecekte ``tech_blog_rss.py`` ayrı.
"""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

# Medium RSS Dublin Core namespace (creator field için).
DC_NS = {"dc": "http://purl.org/dc/elements/1.1/"}
USER_AGENT = "rasathane-bot/1.0 (+https://github.com/aringm/rasathane)"
DEFAULT_TIMEOUT = 15.0
API_BASE = "https://medium.com/feed"

# Phase 35-xvii başlangıç publication listesi.
# Format: feed_path (publication slug veya @username) → tag list.
DEFAULT_PUBLICATIONS: dict[str, list[str]] = {
    "towards-data-science": ["dunya_ai"],
    "better-programming": ["dunya_ai"],
}


def _parse_pubdate(rfc822: str) -> str | None:
    """RFC 822 datetime → ISO 8601.

    Medium `<pubDate>` formatı: ``Wed, 20 May 2026 15:30:00 GMT``.
    Phase 35-xv time filter lexicographic ISO compare bekliyor, RFC 822
    direkt compare çalışmaz (week-day prefix, ay isimleri).
    """
    if not rfc822:
        return None
    try:
        dt = parsedate_to_datetime(rfc822)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    # ISO 8601 UTC, "Z" suffix (lexicographic chronological).
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_medium_feed(
    rss_xml: str, *, publication: str, tags: list[str]
) -> list[dict[str, Any]]:
    """Medium RSS 2.0 feed XML'i parse → list[post dict]."""
    try:
        root = ET.fromstring(rss_xml)
    except ET.ParseError as e:
        log.warning("medium_rss.parse_failed", publication=publication, err=str(e)[:120])
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    out: list[dict[str, Any]] = []
    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        pubdate_el = item.find("pubDate")
        description_el = item.find("description")
        # Dublin Core creator field — Medium'da author bilgisi
        creator_el = item.find("dc:creator", DC_NS)
        if title_el is None or link_el is None:
            continue
        url = (link_el.text or "").strip()
        posted_at = _parse_pubdate(pubdate_el.text or "" if pubdate_el is not None else "")
        # Description HTML — ilk 500 char ham olarak (UI tarafında strip
        # gerekirse eklenir).
        text = (description_el.text or "")[:500] if description_el is not None else ""
        author = (creator_el.text or "").strip() if creator_el is not None else ""
        out.append(
            {
                "title": (title_el.text or "").strip(),
                "url": url,
                "handle": f"medium.com/{publication}",
                "platform": "medium",
                "posted_at": posted_at,
                "text": text,
                "author": author,
                "tags": list(tags),
                "safe": True,
            }
        )
    return out


async def _http_get_rss(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml"},
    ) as client:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.text


def _cache_path(cache_root: Path, publication: str) -> Path:
    # publication slug: alphanumerik + dash/@ → file-safe
    safe = "".join(c for c in publication if c.isalnum() or c in "_-@")
    return cache_root / f"medium_{safe}.json"


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _is_fresh(cached: dict[str, Any], ttl_sec: int) -> bool:
    try:
        dt = datetime.fromisoformat(cached["fetched_at"])
    except (KeyError, ValueError):
        return False
    age = (datetime.now(UTC) - dt).total_seconds()
    return age < ttl_sec


async def fetch_publication(
    publication: str,
    tags: list[str],
    *,
    cache_root: Path,
    cache_ttl_sec: int = 1800,
) -> list[dict[str, Any]]:
    """Tek publication feed'ini çek + cache yaz.

    Cache 30dk TTL. Stale ise re-fetch, network fail'inde stale cache
    fallback (UI çalışmaya devam eder).
    """
    # ASYNC240: pathlib syscall'ı off-thread.
    await asyncio.to_thread(cache_root.mkdir, parents=True, exist_ok=True)
    cache_path = _cache_path(cache_root, publication)
    cached = _read_cache(cache_path)
    if cached and _is_fresh(cached, cache_ttl_sec):
        return cached.get("posts", [])
    url = f"{API_BASE}/{publication}"
    try:
        rss_text = await _http_get_rss(url)
    except (httpx.HTTPError, httpx.HTTPStatusError) as e:
        log.warning("medium_rss.fetch_failed", publication=publication, err=str(e)[:120])
        return (cached or {}).get("posts", [])
    posts = parse_medium_feed(rss_text, publication=publication, tags=tags)
    _write_cache_atomic(
        cache_path,
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "publication": publication,
            "platform": "medium",
            "posts": posts,
        },
    )
    log.info("medium_rss.fetched", publication=publication, count=len(posts))
    return posts


async def fetch_medium_feeds(
    publications: dict[str, list[str]] | None = None,
    *,
    cache_root: Path,
    cache_ttl_sec: int = 1800,
    concurrency: int = 3,
) -> list[dict[str, Any]]:
    """Tüm publication'ları paralel fetch + tek liste döndür.

    Concurrency 3 — Medium anon rate limit yumuşak ama burst protection
    yedeği için.
    """
    feeds = publications if publications is not None else DEFAULT_PUBLICATIONS
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(pub: str, tags: list[str]) -> list[dict[str, Any]]:
        async with sem:
            return await fetch_publication(
                pub, tags, cache_root=cache_root, cache_ttl_sec=cache_ttl_sec
            )

    results = await asyncio.gather(
        *(_guarded(p, t) for p, t in feeds.items()),
        return_exceptions=True,
    )
    all_posts: list[dict[str, Any]] = []
    for res in results:
        if isinstance(res, list):
            all_posts.extend(res)
    all_posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return all_posts

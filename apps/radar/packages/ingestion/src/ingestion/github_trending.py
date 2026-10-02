"""GitHub trending discovery adapter — Phase 35-xviii.

Endpoint: ``https://api.github.com/search/repositories?q=...``
Anon erişim 10 req/dk, JSON response. Mevcut `github_releases.py` sabit
``owner/repo`` watch list pattern'ini tamamlar — bu adapter **otomatik
trending discovery** yapar: topic + stars + pushed filter ile son hafta
aktif popüler repo'ları çeker.

Mimari kuralı: LLM çağrısı yok — yalnız search API + cache I/O.

Query semantic:
    topic:X        → repo'nun GitHub topic tag'lerinden biri X
    stars:>N       → minimum star sayısı (popülerlik filter)
    pushed:>=DATE  → son N gün içinde push olan repo'lar (active filter)
    sort:stars     → en popüler önce
    order:desc     → descending order

DEFAULT_QUERIES (kullanıcı ilgi alanlarına göre):
    topic:llm                → ["dunya_ai"]
    topic:legaltech          → ["legaltech"]
    topic:turkish-nlp        → ["turkiye_ai", "acik_kaynak_ai"]
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

USER_AGENT = "rasathane-bot/1.0 (+https://github.com/aringm/rasathane)"
DEFAULT_TIMEOUT = 20.0
API_BASE = "https://api.github.com/search/repositories"

# Phase 35-xviii başlangıç query set'i. Her query → tag list mapping;
# query'den dönen repo'lar bu tag'lerle işaretlenir. Filter'lar curated:
# stars threshold kullanıcı niş alanlarına göre (legaltech düşük, llm
# yüksek). `pushed_days_ago` query'ye runtime'da inject edilir.
DEFAULT_QUERIES: dict[str, dict[str, Any]] = {
    "llm": {"topic": "llm", "min_stars": 500, "tags": ["dunya_ai"]},
    "ai-agents": {"topic": "agents", "min_stars": 300, "tags": ["dunya_ai"]},
    "open-source-llm": {
        "topic": "open-source-llm",
        "min_stars": 100,
        "tags": ["acik_kaynak_ai", "dunya_ai"],
    },
    "legaltech": {"topic": "legaltech", "min_stars": 30, "tags": ["legaltech"]},
    "turkish-nlp": {
        "topic": "turkish-nlp",
        "min_stars": 10,
        "tags": ["turkiye_ai", "acik_kaynak_ai"],
    },
}


def parse_search_results(
    data: dict[str, Any], *, query_name: str, tags: list[str]
) -> list[dict[str, Any]]:
    """Search API JSON response → list[post dict].

    Repo'nun `pushed_at` field'ı son push zamanı — release'den daha geniş
    semantic ama "aktif repo" sinyali güçlü. Time filter (Phase 35-xv)
    bu field üzerinde çalışır.
    """
    items = data.get("items", []) or []
    out: list[dict[str, Any]] = []
    for repo in items:
        full_name = repo.get("full_name") or ""
        if not full_name:
            continue
        # owner = full_name.split("/")[0]  # Şu an kullanılmıyor, ileride filter için
        out.append(
            {
                "title": full_name,
                "url": repo.get("html_url") or f"https://github.com/{full_name}",
                "handle": full_name,
                "platform": "github",
                "posted_at": repo.get("pushed_at"),
                # description + stars + lang özeti
                "text": (
                    f"{repo.get('description') or 'no description'} "
                    f"| ⭐ {repo.get('stargazers_count', 0)} "
                    f"| {repo.get('language') or 'unknown'}"
                )[:500],
                "tags": list(tags),
                "safe": True,
                # Trending-spesifik meta (ileride UI'da gösterilebilir)
                "_meta": {
                    "stars": repo.get("stargazers_count", 0),
                    "language": repo.get("language"),
                    "query": query_name,
                },
            }
        )
    return out


async def _http_search(url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        },
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


def _build_query_url(
    *,
    topic: str,
    min_stars: int,
    pushed_days_ago: int,
    per_page: int = 30,
) -> str:
    """GitHub search query URL builder."""
    cutoff_date = (datetime.now(UTC) - timedelta(days=pushed_days_ago)).strftime("%Y-%m-%d")
    q = f"topic:{topic} stars:>={min_stars} pushed:>={cutoff_date}"
    # URL encoding — GitHub search expects `+` for space, `>=` URL-safe in query
    from urllib.parse import urlencode

    params = urlencode(
        {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": per_page,
        }
    )
    return f"{API_BASE}?{params}"


def _cache_path(cache_root: Path, query_name: str) -> Path:
    safe = "".join(c for c in query_name if c.isalnum() or c in "_-")
    return cache_root / f"github_trending_{safe}.json"


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


async def fetch_trending_query(
    query_name: str,
    config: dict[str, Any],
    *,
    cache_root: Path,
    cache_ttl_sec: int = 3600,
    pushed_days_ago: int = 7,
) -> list[dict[str, Any]]:
    """Tek search query çek + cache yaz.

    Cache 1 saat (TTL) — trending result GitHub'da daha sıklıkla değişmez.
    Rate limit 10 req/dk anon, paralel discovery için TTL geniş.
    """
    await asyncio.to_thread(cache_root.mkdir, parents=True, exist_ok=True)
    cache_path = _cache_path(cache_root, query_name)
    cached = _read_cache(cache_path)
    if cached and _is_fresh(cached, cache_ttl_sec):
        return cached.get("posts", [])
    url = _build_query_url(
        topic=config["topic"],
        min_stars=config["min_stars"],
        pushed_days_ago=pushed_days_ago,
    )
    try:
        data = await _http_search(url)
    except (httpx.HTTPError, httpx.HTTPStatusError) as e:
        log.warning(
            "github_trending.fetch_failed",
            query=query_name,
            err=str(e)[:120],
        )
        return (cached or {}).get("posts", [])
    posts = parse_search_results(data, query_name=query_name, tags=config["tags"])
    _write_cache_atomic(
        cache_path,
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "query": query_name,
            "platform": "github",
            "posts": posts,
        },
    )
    log.info("github_trending.fetched", query=query_name, count=len(posts))
    return posts


async def fetch_trending_feeds(
    queries: dict[str, dict[str, Any]] | None = None,
    *,
    cache_root: Path,
    cache_ttl_sec: int = 3600,
    pushed_days_ago: int = 7,
    concurrency: int = 2,
) -> list[dict[str, Any]]:
    """Tüm query'leri paralel fetch et + tek liste.

    Concurrency 2 — GitHub search rate limit 10 req/dk anon, marj geniş
    tut (burst protection). 5 query × 1 call = 5 req, dakikalık limit
    içinde rahat.
    """
    feeds = queries if queries is not None else DEFAULT_QUERIES
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(name: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        async with sem:
            return await fetch_trending_query(
                name,
                cfg,
                cache_root=cache_root,
                cache_ttl_sec=cache_ttl_sec,
                pushed_days_ago=pushed_days_ago,
            )

    results = await asyncio.gather(
        *(_guarded(n, c) for n, c in feeds.items()),
        return_exceptions=True,
    )
    all_posts: list[dict[str, Any]] = []
    for res in results:
        if isinstance(res, list):
            all_posts.extend(res)
    all_posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return all_posts

"""Reddit OAuth adapter — Phase 35-xxi (Phase 35-xvi rewrite).

Phase 35-xvi anon RSS endpoint (`/r/X/hot/.rss`) Reddit anti-bot
korumasıyla 403 Blocked veriyordu (generic User-Agent reddedildi).
Bu modül **OAuth client_credentials grant** ile authenticated JSON
API'ye geçer:

    1. POST https://www.reddit.com/api/v1/access_token  (basic auth)
       body: grant_type=client_credentials
    2. GET  https://oauth.reddit.com/r/{name}/hot.json?limit=25
       header: Authorization: Bearer <token>

Token 1 saatlik (`expires_in: 3600`); modül-level cache ile her
adapter çağrısında yeni token istemez. 100 req/dk auth'lı limit
(anon RSS'in 60 req/dk'sından yüksek).

Env vars (kullanıcı `.env` ile sağlar):
    REDDIT_CLIENT_ID      — "personal use script" string (https://reddit.com/prefs/apps)
    REDDIT_CLIENT_SECRET  — app secret
    REDDIT_USER_AGENT     — örn. "rasathane/1.0 by u/aringm"

Mimari kuralı: LLM çağrısı yok — yalnız OAuth + JSON parse + cache I/O.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

DEFAULT_TIMEOUT = 15.0
TOKEN_ENDPOINT = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com/r"

# Phase 35-xvi başlangıç subreddit listesi (Phase 35-xxi'de korundu).
DEFAULT_SUBREDDITS: dict[str, list[str]] = {
    "MachineLearning": ["dunya_ai"],
    "LocalLLaMA": ["acik_kaynak_ai", "dunya_ai"],
    "artificial": ["dunya_ai"],
    "LegalTechnology": ["legaltech"],
    "lawyertalk": ["legaltech"],
    "Turkey": ["turkiye_ai"],
    "Turkiye": ["turkiye_ai"],
}

# Module-level token cache — adapter çağrısı başına yeni token istemez.
# Reddit token 3600s yaşar; biz 3500s threshold ile expire eder (safety margin).
_TOKEN_CACHE: dict[str, Any] = {"token": None, "expires_at": 0.0}
_TOKEN_LIFETIME_BUFFER_S = 100  # 1 dakika erken refresh


def _get_credentials() -> tuple[str, str, str]:
    """Env'den OAuth credentials çek. Eksikse RuntimeError."""
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = os.environ.get("REDDIT_USER_AGENT", "").strip()
    if not (client_id and client_secret and user_agent):
        raise RuntimeError(
            "Reddit OAuth env vars eksik: REDDIT_CLIENT_ID, "
            "REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT. "
            "Setup: https://www.reddit.com/prefs/apps → create app → "
            "type=script."
        )
    return client_id, client_secret, user_agent


async def _fetch_token() -> str:
    """OAuth2 client_credentials grant ile token al + cache yaz.

    Reddit token endpoint basic auth (client_id:client_secret) + body
    grant_type=client_credentials. Response 1 saatlik bearer token.
    """
    now = datetime.now(UTC).timestamp()
    cached = _TOKEN_CACHE.get("token")
    if cached and _TOKEN_CACHE.get("expires_at", 0) > now + _TOKEN_LIFETIME_BUFFER_S:
        return cached
    client_id, client_secret, user_agent = _get_credentials()
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": user_agent},
        auth=httpx.BasicAuth(client_id, client_secret),
    ) as client:
        r = await client.post(
            TOKEN_ENDPOINT,
            data={"grant_type": "client_credentials"},
        )
        r.raise_for_status()
        payload = r.json()
    token = payload.get("access_token")
    expires_in = int(payload.get("expires_in", 3600))
    if not token:
        raise RuntimeError(f"Reddit token response invalid: {payload}")
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + expires_in
    log.info("reddit_oauth.token_refreshed", expires_in=expires_in)
    return token


def parse_reddit_listing(
    payload: dict[str, Any], *, subreddit: str, tags: list[str]
) -> list[dict[str, Any]]:
    """Reddit JSON listing → list[post dict].

    Schema (auth API):
        {"kind": "Listing", "data": {"children": [{"kind": "t3", "data": {...post...}}]}}

    Post data field'ları: title, permalink, author, created_utc (Unix sec),
    selftext, score, num_comments, subreddit, ups.
    """
    data_block = payload.get("data") or {}
    children = data_block.get("children") or []
    out: list[dict[str, Any]] = []
    for child in children:
        if child.get("kind") != "t3":
            continue  # Sadece submission'lar; comment'leri atla
        post = child.get("data") or {}
        title = post.get("title") or ""
        permalink = post.get("permalink") or ""
        if not title or not permalink:
            continue
        # created_utc Unix saniye → ISO 8601 UTC Z-suffix
        created = post.get("created_utc")
        posted_at: str | None = None
        if isinstance(created, int | float) and created > 0:
            posted_at = (
                datetime.fromtimestamp(created, UTC).isoformat().replace("+00:00", "Z")
            )
        # selftext post body — ilk 500 char (UI sanitize gerekirse ekle)
        text = (post.get("selftext") or "")[:500]
        out.append(
            {
                "title": title,
                "url": f"https://www.reddit.com{permalink}",
                "handle": f"r/{subreddit}",
                "platform": "reddit",
                "posted_at": posted_at,
                "text": text,
                "author": post.get("author") or "",
                "tags": list(tags),
                "safe": True,
                # Bonus meta — gelecek UI'da gösterim için
                "_meta": {
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                },
            }
        )
    return out


async def _http_get_listing(url: str, token: str, user_agent: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={
            "User-Agent": user_agent,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


def _cache_path(cache_root: Path, subreddit: str) -> Path:
    safe = "".join(c for c in subreddit if c.isalnum() or c in "_-")
    return cache_root / f"reddit_{safe}.json"


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


async def fetch_subreddit(
    subreddit: str,
    tags: list[str],
    *,
    cache_root: Path,
    cache_ttl_sec: int = 1800,
) -> list[dict[str, Any]]:
    """Tek subreddit'in /hot JSON listesi çek + cache yaz.

    OAuth token cache'lenir; ilk fetch'te token alır, sonrakiler reuse.
    Network/auth fail → stale cache fallback (UI pipeline durmaz).
    """
    await asyncio.to_thread(cache_root.mkdir, parents=True, exist_ok=True)
    cache_path = _cache_path(cache_root, subreddit)
    cached = _read_cache(cache_path)
    if cached and _is_fresh(cached, cache_ttl_sec):
        return cached.get("posts", [])
    try:
        token = await _fetch_token()
        _, _, user_agent = _get_credentials()
    except (RuntimeError, httpx.HTTPError) as e:
        log.warning("reddit_oauth.auth_failed", subreddit=subreddit, err=str(e)[:120])
        return (cached or {}).get("posts", [])
    url = f"{API_BASE}/{subreddit}/hot?limit=25"
    try:
        payload = await _http_get_listing(url, token, user_agent)
    except (httpx.HTTPError, httpx.HTTPStatusError) as e:
        log.warning(
            "reddit_oauth.fetch_failed", subreddit=subreddit, err=str(e)[:120]
        )
        return (cached or {}).get("posts", [])
    posts = parse_reddit_listing(payload, subreddit=subreddit, tags=tags)
    _write_cache_atomic(
        cache_path,
        {
            "fetched_at": datetime.now(UTC).isoformat(),
            "subreddit": subreddit,
            "platform": "reddit",
            "posts": posts,
        },
    )
    log.info("reddit_oauth.fetched", subreddit=subreddit, count=len(posts))
    return posts


async def fetch_reddit_feeds(
    subreddits: dict[str, list[str]] | None = None,
    *,
    cache_root: Path,
    cache_ttl_sec: int = 1800,
    concurrency: int = 3,
) -> list[dict[str, Any]]:
    """Tüm subreddit'leri paralel fetch + tek liste döndür.

    Concurrency 3 — Reddit auth'lı 100 req/dk; 7 subreddit × 1 = 7 req
    per sync, limit içinde rahat. Token cache shared (asyncio.gather
    parallel fetch içinde aynı token reuse — race condition yok).
    """
    feeds = subreddits if subreddits is not None else DEFAULT_SUBREDDITS
    sem = asyncio.Semaphore(concurrency)

    async def _guarded(sub: str, tags: list[str]) -> list[dict[str, Any]]:
        async with sem:
            return await fetch_subreddit(
                sub, tags, cache_root=cache_root, cache_ttl_sec=cache_ttl_sec
            )

    results = await asyncio.gather(
        *(_guarded(s, t) for s, t in feeds.items()),
        return_exceptions=True,
    )
    all_posts: list[dict[str, Any]] = []
    for res in results:
        if isinstance(res, list):
            all_posts.extend(res)
    all_posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return all_posts

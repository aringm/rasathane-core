"""HuggingFace model release adapter — Phase 33-ii.

Endpoint: `https://huggingface.co/api/models?author={author}&sort=createdAt&limit=20`
Anon erişim, rate limit 10 req/dk. Cache pattern github_releases.py ile simetrik.

Mimari kuralı: LLM çağrısı yok.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

USER_AGENT = "rasathane-bot/1.0 (+https://github.com/aringm/rasathane)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_TAGS = ["acik_kaynak_ai", "dunya_ai"]
API_BASE = "https://huggingface.co/api/models"


def parse_hf_response(items: list[dict[str, Any]], *, author: str) -> list[dict[str, Any]]:
    """HF API response (list of model dicts) → normalized post list."""
    out: list[dict[str, Any]] = []
    for it in items:
        model_id = it.get("id") or ""
        if not model_id:
            continue
        # `author/model-name` → `model-name`
        title = model_id.split("/", 1)[1] if "/" in model_id else model_id
        out.append(
            {
                "title": title,
                "url": f"https://huggingface.co/{model_id}",
                "handle": author,
                "platform": "huggingface",
                # Phase 35-xiv: HF API response'unda `lastModified` field yok;
                # `createdAt` (model upload zamanı, ISO 8601 UTC) authoritative.
                # `sort=createdAt&direction=-1` query'siyle de tutarlı. Defansif
                # olarak `lastModified` fallback'i tutuluyor — API ileride o
                # field'ı eklerse desteklenir.
                "posted_at": it.get("createdAt") or it.get("lastModified"),
                "text": f"pipeline: {it.get('pipeline_tag', 'n/a')}, downloads: {it.get('downloads', 0)}",
                "tags": list(DEFAULT_TAGS),
                "safe": True,
            }
        )
    return out


async def _http_get_json(url: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()


def _cache_path(cache_root: Path, author: str) -> Path:
    safe = "".join(c for c in author if c.isalnum() or c in "_-")
    return cache_root / f"hf_{safe}.json"


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
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
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds() < ttl_sec


async def fetch_hf_models(
    authors: list[str],
    *,
    cache_root: Path,
    cache_ttl_sec: int = 1800,
) -> list[dict[str, Any]]:
    """Author listesi için son model release'leri cache-first toplar."""
    # ASYNC240: pathlib syscall'ı off-thread (event loop'u bloklamasın).
    await asyncio.to_thread(cache_root.mkdir, parents=True, exist_ok=True)
    all_posts: list[dict[str, Any]] = []
    # HF anon rate limit 10/dk; sequential fetch with 1s sleep to stay safe
    sem = asyncio.Semaphore(2)  # 2 concurrent

    async def _fetch_one(author: str) -> list[dict[str, Any]]:
        cache_file = _cache_path(cache_root, author)
        cached = _read_cache(cache_file)
        if cached and _is_fresh(cached, cache_ttl_sec):
            return cached.get("posts", [])
        url = f"{API_BASE}?author={author}&sort=createdAt&direction=-1&limit=20"
        try:
            items = await _http_get_json(url)
        except (httpx.HTTPError, httpx.HTTPStatusError) as e:
            log.warning("hf_models.fetch_failed", author=author, err=str(e)[:120])
            if cached:
                return cached.get("posts", [])
            return []
        posts = parse_hf_response(items, author=author)
        _write_cache_atomic(
            cache_file,
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "posts": posts,
                "handle": author,
                "platform": "huggingface",
            },
        )
        return posts

    async def _guarded(a: str) -> list[dict[str, Any]]:
        async with sem:
            return await _fetch_one(a)

    results = await asyncio.gather(*(_guarded(a) for a in authors), return_exceptions=True)
    for res in results:
        if isinstance(res, list):
            all_posts.extend(res)

    all_posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return all_posts

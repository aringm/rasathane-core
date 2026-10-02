"""GitHub release feed adapter — Phase 33-ii.

Public GitHub repos için `releases.atom` feed'i — auth-free, 60 req/hr anon
rate limit. Cache pattern `social_posts.py` ile simetrik.

Mimari kuralı: LLM çağrısı yok — yalnız RSS parse + cache I/O.
"""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
USER_AGENT = "rasathane-bot/1.0 (+https://github.com/aringm/rasathane)"
DEFAULT_TIMEOUT = 15.0
DEFAULT_TAGS = ["acik_kaynak_ai"]


def _safe_handle(handle: str) -> str:
    """`owner/repo` → `owner_repo` (filename-safe)."""
    return handle.replace("/", "_").replace("\\", "_")


def parse_atom(atom_xml: str, *, handle: str) -> list[dict[str, Any]]:
    """Atom feed XML'i parse → list[post dict]."""
    try:
        root = ET.fromstring(atom_xml)
    except ET.ParseError as e:
        log.warning("github_releases.parse_failed", handle=handle, err=str(e)[:120])
        return []

    out: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        title_el = entry.find("atom:title", ATOM_NS)
        link_el = entry.find("atom:link", ATOM_NS)
        updated_el = entry.find("atom:updated", ATOM_NS)
        content_el = entry.find("atom:content", ATOM_NS)
        if title_el is None or link_el is None:
            continue
        href = link_el.get("href", "")
        posted_at = updated_el.text if updated_el is not None and updated_el.text else None
        out.append(
            {
                "title": title_el.text or "",
                "url": href,
                "handle": handle,
                "platform": "github",
                "posted_at": posted_at,
                "text": (content_el.text or "")[:500] if content_el is not None else "",
                "tags": list(DEFAULT_TAGS),
                "safe": True,  # GitHub release notları structured, prompt injection riski düşük
            }
        )
    return out


async def _http_get_atom(url: str) -> str:
    async with httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/atom+xml"},
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.text


def _cache_path(cache_root: Path, handle: str) -> Path:
    return cache_root / f"github_{_safe_handle(handle)}.json"


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


async def fetch_github_releases(
    handles: list[str],
    *,
    cache_root: Path,
    cache_ttl_sec: int = 1800,
) -> list[dict[str, Any]]:
    """Handle listesinin son release'lerini cache-first toplar.

    Args:
        handles: `["owner/repo", ...]` formatında.
        cache_root: cache dosyalarının yaşadığı dizin (mkdir guaranteed by caller).
        cache_ttl_sec: 1800 default (30 dk).

    Returns:
        Time-sorted desc post list, tüm handle'lar birleşik.
    """
    # ASYNC240: pathlib syscall'ı off-thread (event loop'u bloklamasın).
    await asyncio.to_thread(cache_root.mkdir, parents=True, exist_ok=True)
    all_posts: list[dict[str, Any]] = []

    async def _fetch_one(handle: str) -> list[dict[str, Any]]:
        cache_file = _cache_path(cache_root, handle)
        cached = _read_cache(cache_file)
        if cached and _is_fresh(cached, cache_ttl_sec):
            return cached.get("posts", [])

        url = f"https://github.com/{handle}/releases.atom"
        try:
            xml_text = await _http_get_atom(url)
        except (httpx.HTTPError, httpx.HTTPStatusError) as e:
            log.warning("github_releases.fetch_failed", handle=handle, err=str(e)[:120])
            if cached:
                return cached.get("posts", [])
            return []

        posts = parse_atom(xml_text, handle=handle)
        _write_cache_atomic(
            cache_file,
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "posts": posts,
                "handle": handle,
                "platform": "github",
            },
        )
        return posts

    # Paralel fetch (concurrency 5)
    sem = asyncio.Semaphore(5)

    async def _guarded(h: str) -> list[dict[str, Any]]:
        async with sem:
            return await _fetch_one(h)

    results = await asyncio.gather(*(_guarded(h) for h in handles), return_exceptions=True)
    for res in results:
        if isinstance(res, list):
            all_posts.extend(res)

    # Time-sorted desc
    all_posts.sort(key=lambda p: p.get("posted_at") or "", reverse=True)
    return all_posts

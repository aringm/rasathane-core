"""Sosyal medya kişi paylaşımları — cache + fetch orkestrasyon.

Phase 32-i.3: `/api/social-watch/{person_id}/posts` endpoint'inin
arka katmanı. Nitter fetch'i pahalı + kırılgan olduğu için filesystem
cache zorunlu. 30 dakika TTL; stale fallback canlı fetch fail ederse.

Filesystem layout:
    archive/social_watch_cache/{person_id}.json
        {"fetched_at": "2026-05-17T...", "posts": [...], "handle": "@x",
         "platform": "x", "source": "nitter"}

Mimari kuralı korundu:
    - Bu modül LLM çağırmaz. Sadece I/O + cache.
    - Paylaşım metni `social_watch.is_safe_for_llm` ile pre-filter
      edilir → her post'a `safe` flag eklenir; UI buna göre uyarı gösterir.
    - Cache yazımı atomic (temp file + rename) — partial yazım yok.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog

from rasathane_mcp.core import social_watch as core_social_watch

log = structlog.get_logger()

CACHE_TTL_SECONDS = 1800  # 30 dakika
STALE_FALLBACK_TTL_SECONDS = 86400  # 24 saat (canlı fetch fail ederse buradan döner)


PostSource = Literal["nitter", "cache", "stale_cache", "unavailable"]


def _cache_dir(archive_root: Path) -> Path:
    p = archive_root / "social_watch_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _cache_path(archive_root: Path, person_id: str) -> Path:
    # person_id zaten `[a-z0-9_]` pattern'ine uyuyor (Pydantic doğrular)
    safe = "".join(c for c in person_id if c.isalnum() or c == "_")
    return _cache_dir(archive_root) / f"{safe}.json"


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("social_posts.cache_read_failed", path=str(path), err=str(e)[:120])
        return None


def _write_cache_atomic(path: Path, data: dict[str, Any]) -> None:
    """Temp dosya + rename — yarım yazım kalmaz."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _annotate_safety(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Her post'a `safe` bool + `injection_hits` ekle.

    Defense-in-depth: post metni LLM'e talimat olarak yorumlanmaz.
    UI bu flag'i kullanarak uyarı banner gösterir; metin yine de
    görüntülenir (kullanıcı görmek istiyor), ama "ajan bunu komut
    olarak algılamaz" sözleşmesi UI'da net.
    """
    annotated: list[dict[str, Any]] = []
    for p in posts:
        safe, hits = core_social_watch.is_safe_for_llm(p.get("text") or "")
        annotated.append({**p, "safe": safe, "injection_hits": hits if hits else None})
    return annotated


def _age_seconds(iso_ts: str) -> float:
    """Cache yaş hesabı — UTC kıyaslı, naive datetime sorunlarına dayanıklı."""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return float("inf")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return (datetime.now(UTC) - dt).total_seconds()


async def get_recent_posts(
    *,
    person_id: str,
    archive_root: Path,
    limit: int = 10,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Kişi paylaşımlarını getir — cache-first, fallback Nitter.

    Returns:
        {
          "person_id": "karpathy",
          "handle": "@karpathy",
          "platform": "x",
          "source": "cache" | "nitter" | "stale_cache" | "unavailable",
          "fetched_at": "ISO timestamp",
          "posts": [...],
          "stale_seconds": <int> | None,
          "warning": <str> | None,
        }

    `posts` her zaman boş liste olabilir (kişi yok / fetch fail / instance
    down). UI bu durumu graceful gösterir.
    """
    # 1. Kişiyi bul (yaml'dan)
    person = core_social_watch.find_person(person_id)
    if person is None:
        return {
            "person_id": person_id,
            "handle": None,
            "platform": None,
            "source": "unavailable",
            "posts": [],
            "warning": "person not found in social_watch.yaml",
        }

    handle = person.handle
    platform = person.platform
    cache_path = _cache_path(archive_root, person_id)

    # 2. Fresh cache (TTL içinde) → direkt döndür
    cached = _read_cache(cache_path)
    if cached and not force_refresh:
        age = _age_seconds(cached.get("fetched_at", ""))
        if age < CACHE_TTL_SECONDS:
            return {
                "person_id": person_id,
                "handle": handle,
                "platform": platform,
                "source": "cache",
                "fetched_at": cached.get("fetched_at"),
                "posts": cached.get("posts", []),
                "stale_seconds": int(age),
                "warning": None,
            }

    # 3. Platform desteklenmiyor (X dışı) → cache'i (varsa) döndür
    if platform != "x":
        return {
            "person_id": person_id,
            "handle": handle,
            "platform": platform,
            "source": "unavailable",
            "posts": cached.get("posts", []) if cached else [],
            "warning": f"platform '{platform}' için fetch adapter yok; sadece X destekleniyor",
        }

    # 4. Live fetch (Nitter)
    from ingestion.nitter import NitterUnavailableError, fetch_recent_tweets

    try:
        raw_posts = await fetch_recent_tweets(handle, limit=limit)
        annotated = _annotate_safety(raw_posts)
        now_iso = datetime.now(UTC).isoformat()
        payload = {
            "person_id": person_id,
            "handle": handle,
            "platform": platform,
            "source": "nitter",
            "fetched_at": now_iso,
            "posts": annotated,
            "stale_seconds": 0,
            "warning": None,
        }
        # Cache'e yaz (atomic)
        _write_cache_atomic(
            cache_path,
            {
                "fetched_at": now_iso,
                "handle": handle,
                "platform": platform,
                "source": "nitter",
                "posts": annotated,
            },
        )
        return payload
    except NitterUnavailableError as e:
        # 5. Stale cache fallback — 24 saat içindeyse döndür
        if cached:
            age = _age_seconds(cached.get("fetched_at", ""))
            if age < STALE_FALLBACK_TTL_SECONDS:
                return {
                    "person_id": person_id,
                    "handle": handle,
                    "platform": platform,
                    "source": "stale_cache",
                    "fetched_at": cached.get("fetched_at"),
                    "posts": cached.get("posts", []),
                    "stale_seconds": int(age),
                    "warning": f"Nitter geçici olarak ulaşılamıyor; {int(age // 60)} dk önceki "
                    f"cache gösteriliyor. Detay: {str(e)[:140]}",
                }
        # 6. Hiçbir veri yok
        return {
            "person_id": person_id,
            "handle": handle,
            "platform": platform,
            "source": "unavailable",
            "posts": [],
            "warning": f"Nitter ulaşılamıyor + cache yok. {str(e)[:200]}",
        }

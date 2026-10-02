"""Phase 33-ii: /api/social-watch/feed — tüm handle'ların time-sorted agg.

Endpoint tüm cache dosyalarını (``github_*.json``, ``hf_*.json``, eski
Nitter cache pattern) okur, ``posted_at`` DESC sıralar, tag filter
uygular. Fresh fetch YAPMAZ — ``pulse sync`` cron responsible.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def cache_with_posts(tmp_path: Path) -> Path:
    """Birkaç cache dosyası yaz — feed agg testi için.

    Phase 35-xii: timestamp'leri ``datetime.now`` relative — endpoint
    default ``since_hours=24`` filter'ı kapsamına girsin (önceki hardcoded
    "2026-05-19T14:00:00" tarihleri test çalıştırma zamanına göre 24+
    saat eskidiği için filter'a takılıyordu).
    """
    archive_dir = tmp_path / "archive"
    cache_dir = archive_dir / "social_watch_cache"
    cache_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    # Posts: biri 4 saat önce, diğeri 2 saat önce — ikisi de since_hours=24'ün içinde.
    deepseek_iso = (now - timedelta(hours=4)).isoformat()
    qwen_iso = (now - timedelta(hours=2)).isoformat()
    (cache_dir / "github_deepseek-ai_DeepSeek-V3.json").write_text(
        json.dumps(
            {
                "fetched_at": now_iso,
                "posts": [
                    {
                        "title": "v0.4.2",
                        "url": "https://gh",
                        "handle": "deepseek-ai/DeepSeek-V3",
                        "platform": "github",
                        "posted_at": deepseek_iso,
                        "tags": ["acik_kaynak_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (cache_dir / "hf_Qwen.json").write_text(
        json.dumps(
            {
                "fetched_at": now_iso,
                "posts": [
                    {
                        "title": "Qwen3-72B",
                        "url": "https://hf",
                        "handle": "Qwen",
                        "platform": "huggingface",
                        "posted_at": qwen_iso,
                        "tags": ["acik_kaynak_ai", "dunya_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return archive_dir


@pytest.fixture
def app() -> Any:
    from rasathane_mcp.dashboard.app import create_app

    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_social_watch_feed_aggregates_and_sorts(
    cache_with_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_posts)
    async with client:
        r = await client.get("/api/social-watch/feed")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "posts" in body
    assert body["count"] == 2
    # Newer first (Qwen 16:00 > DeepSeek 14:00)
    assert body["posts"][0]["title"] == "Qwen3-72B"
    assert body["posts"][1]["title"] == "v0.4.2"


@pytest.mark.asyncio
async def test_social_watch_feed_tag_filter(
    cache_with_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_posts)
    async with client:
        r = await client.get("/api/social-watch/feed?tag=dunya_ai")
    assert r.status_code == 200, r.text
    body = r.json()
    # Sadece dunya_ai tag'i olan Qwen kalır
    assert body["count"] == 1
    assert body["posts"][0]["title"] == "Qwen3-72B"


@pytest.mark.asyncio
async def test_social_watch_feed_empty_when_cache_dir_missing(
    tmp_path: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache dir hiç yoksa boş envelope (200) döner."""
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)
    async with client:
        r = await client.get("/api/social-watch/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["posts"] == []


@pytest.mark.asyncio
async def test_social_watch_feed_pagination(
    cache_with_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """limit+offset doğru çalışıyor; next_offset uygun şekilde set."""
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_posts)
    async with client:
        r = await client.get("/api/social-watch/feed?limit=1")
        body = r.json()
        assert body["count"] == 1
        assert body["total"] == 2
        assert body["next_offset"] == 1
        # Second page (within same client context)
        r2 = await client.get("/api/social-watch/feed?limit=1&offset=1")
        body2 = r2.json()
        assert body2["count"] == 1
        assert body2["posts"][0]["title"] == "v0.4.2"
        assert body2["next_offset"] is None


# ── Phase 35-xii: since_hours time window filter ────────────────────────


@pytest.fixture
def cache_with_old_and_fresh_posts(tmp_path: Path) -> Path:
    """1 fresh post (son 24 sa içinde) + 1 stale post (1 yıl önce)."""
    archive_dir = tmp_path / "archive"
    cache_dir = archive_dir / "social_watch_cache"
    cache_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    fresh_iso = (now - timedelta(hours=2)).isoformat()
    stale_iso = (now - timedelta(days=365)).isoformat()
    (cache_dir / "github_fresh.json").write_text(
        json.dumps(
            {
                "fetched_at": now.isoformat(),
                "posts": [
                    {
                        "title": "Fresh Release",
                        "url": "https://gh/fresh",
                        "handle": "test/fresh",
                        "platform": "github",
                        "posted_at": fresh_iso,
                        "tags": ["acik_kaynak_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (cache_dir / "github_stale.json").write_text(
        json.dumps(
            {
                "fetched_at": now.isoformat(),
                "posts": [
                    {
                        "title": "Stale Release 1 year ago",
                        "url": "https://gh/stale",
                        "handle": "test/stale",
                        "platform": "github",
                        "posted_at": stale_iso,
                        "tags": ["acik_kaynak_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return archive_dir


@pytest.mark.asyncio
async def test_since_hours_default_filters_old_posts(
    cache_with_old_and_fresh_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 35-xv: default since_hours=168 (1 hafta) → 1 yıl önceki post hariç.

    Önceki davranış (Phase 33-ii): hiç time filter yoktu. Phase 35-xii'de
    24 saat default eklendi → HF release cadence için çok dar pencere
    sosyal medya tab'ı boş bırakıyordu. Phase 35-xv default 168 saat
    (1 hafta). Stale handle'lar ayrı section'da gösterilir.
    """
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_old_and_fresh_posts
    )
    async with client:
        r = await client.get("/api/social-watch/feed")
    body = r.json()
    assert body["count"] == 1
    assert body["posts"][0]["title"] == "Fresh Release"
    assert body["since_hours"] == 168


@pytest.mark.asyncio
async def test_since_hours_zero_returns_all_history(
    cache_with_old_and_fresh_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """since_hours=0 → time filter atlanır, tüm cache history döner.

    Geriye dönük query için escape hatch (örn. arşiv eski post'ları
    incele). UI default'ta 24 kullanır.
    """
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_old_and_fresh_posts
    )
    async with client:
        r = await client.get("/api/social-watch/feed?since_hours=0")
    body = r.json()
    assert body["count"] == 2
    assert body["since_hours"] == 0


@pytest.mark.asyncio
async def test_since_hours_custom_value(
    cache_with_old_and_fresh_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """since_hours=1 → 2 saat önceki fresh post bile filtrelenir (boş feed)."""
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_old_and_fresh_posts
    )
    async with client:
        r = await client.get("/api/social-watch/feed?since_hours=1")
    body = r.json()
    assert body["count"] == 0
    assert body["since_hours"] == 1


# ── Phase 35-xv: stale_handles section ─────────────────────────────────


@pytest.mark.asyncio
async def test_stale_handles_returned_for_out_of_window_sources(
    cache_with_old_and_fresh_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 35-xv: window dışı handle'ların son post + days_ago listelenir.

    Kullanıcı UX gereksinim: "bir haftadan fazla süredir gönderi yapmayan
    kaynak olursa onunda son gönderi ve tarihini listeleyelim". Frontend
    UI'da "Sessiz Kaynaklar" section'ı bu listeyi render eder; kullanıcı
    eski aktivite olan kaynakların "dead" olmadığını görür.
    """
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_old_and_fresh_posts
    )
    async with client:
        r = await client.get("/api/social-watch/feed?since_hours=168")
    body = r.json()
    assert "stale_handles" in body
    # 1 fresh handle (window içinde) → posts'ta
    # 1 stale handle (1 yıl önce) → stale_handles'ta
    assert body["count"] == 1
    assert len(body["stale_handles"]) == 1
    stale = body["stale_handles"][0]
    assert stale["handle"] == "test/stale"
    assert stale["platform"] == "github"
    assert stale["days_ago"] >= 360  # ~365 gün önce
    assert stale["last_post"]["title"] == "Stale Release 1 year ago"


@pytest.mark.asyncio
async def test_stale_handles_empty_when_no_filter(
    cache_with_old_and_fresh_posts: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """since_hours=0 → tüm post'lar recent, stale_handles boş."""
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.ARCHIVE_ROOT", cache_with_old_and_fresh_posts
    )
    async with client:
        r = await client.get("/api/social-watch/feed?since_hours=0")
    body = r.json()
    assert body["count"] == 2
    assert body["stale_handles"] == []


# ── Phase 35-xix: Nitter/X eski schema normalize ────────────────────────


@pytest.mark.asyncio
async def test_endpoint_normalizes_old_nitter_schema(
    tmp_path: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 35-xix: eski Nitter cache (karpathy.json gibi) UI'da görünür.

    Karpathy cache şeması farklı: `published_at` (yeni: `posted_at`),
    `author` (yeni: `handle`), platform field yok. Endpoint normalize
    eder — eski cache UI'da düzgün render olur, X post'lar Canlı Akış'ta
    görünür.
    """
    archive_dir = tmp_path / "archive"
    cache_dir = archive_dir / "social_watch_cache"
    cache_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    fresh_iso = (now - timedelta(hours=3)).isoformat()
    # Eski Nitter cache şeması — karpathy.json'la birebir
    (cache_dir / "karpathy.json").write_text(
        json.dumps(
            {
                "fetched_at": now.isoformat(),
                "posts": [
                    {
                        "id": "1234567890",
                        "url": "https://nitter.net/karpathy/status/1234567890",
                        "text": "Llama 4 fine-tuning trick: gradient checkpointing + QLoRA",
                        "author": "karpathy",
                        "published_at": fresh_iso,
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", archive_dir)
    async with client:
        r = await client.get("/api/social-watch/feed?since_hours=168")
    body = r.json()
    assert body["count"] == 1
    p = body["posts"][0]
    # Normalize: published_at → posted_at
    assert p["posted_at"] == fresh_iso
    # Normalize: author → handle
    assert p["handle"] == "karpathy"
    # Normalize: platform default = "x"
    assert p["platform"] == "x"
    # Normalize: title text'in ilk 140 char'ı
    assert "Llama 4" in p["title"]
    # Normalize: default tags ["dunya_ai"]
    assert "dunya_ai" in p["tags"]


@pytest.mark.asyncio
async def test_stale_handles_skips_undated_posts(
    tmp_path: Path,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """posted_at null/missing post'lar stale_handles'a girmemeli.

    Karpathy Nitter/X cache'inde tüm post'ların posted_at null (Phase 35-xix'da
    fix edilecek). Stale UI 'X gün önce' gösteremeyeceği için bu handle'lar
    listede yer almamalı — karışıklık yaratır.
    """
    archive_dir = tmp_path / "archive"
    cache_dir = archive_dir / "social_watch_cache"
    cache_dir.mkdir(parents=True)
    now = datetime.now(UTC)
    (cache_dir / "karpathy.json").write_text(
        json.dumps(
            {
                "fetched_at": now.isoformat(),
                "posts": [
                    {
                        "title": "Nitter post no date",
                        "url": "https://x/post1",
                        "handle": "karpathy",
                        "platform": "x",
                        "posted_at": None,
                        "tags": ["dunya_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", archive_dir)
    async with client:
        r = await client.get("/api/social-watch/feed?since_hours=168")
    body = r.json()
    assert body["stale_handles"] == []  # karpathy null-dated → skip

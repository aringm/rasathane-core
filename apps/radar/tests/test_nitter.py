"""Phase 32-i.3: Nitter scraper testleri (network mock'lu)."""

from __future__ import annotations

import pytest
import respx
from httpx import ConnectError, Response, TimeoutException
from ingestion.nitter import (
    NitterUnavailableError,
    _get_instances,
    _normalize_handle,
    _parse_rss,
    fetch_recent_tweets,
)

# ── Pure helpers ─────────────────────────────────────────────────────────


def test_normalize_handle_strips_at_and_whitespace() -> None:
    assert _normalize_handle("@karpathy") == "karpathy"
    assert _normalize_handle("  @simonw  ") == "simonw"
    assert _normalize_handle("plainuser") == "plainuser"
    # lstrip("@") tüm leading '@'leri çıkarır — "@@x" → "x"
    assert _normalize_handle("@@x") == "x"
    assert _normalize_handle("") == ""


def test_get_instances_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NITTER_INSTANCES", "https://a.example, https://b.example")
    items = _get_instances()
    assert items == ("https://a.example", "https://b.example")


def test_get_instances_empty_env_falls_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NITTER_INSTANCES", "")
    items = _get_instances()
    assert len(items) >= 3
    assert any("nitter" in i for i in items)


def test_parse_rss_basic() -> None:
    """Standard RSS yapısı parse ediliyor — id/url/text/published_at."""
    sample = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <title>@karpathy</title>
      <item>
        <title>Hello world from RSS</title>
        <link>https://nitter.example/karpathy/status/1</link>
        <pubDate>Sat, 17 May 2026 12:00:00 GMT</pubDate>
        <guid>https://nitter.example/karpathy/status/1</guid>
      </item>
      <item>
        <title>Second tweet</title>
        <link>https://nitter.example/karpathy/status/2</link>
        <pubDate>Sat, 17 May 2026 13:00:00 GMT</pubDate>
      </item>
    </channel></rss>"""
    items = _parse_rss(sample, limit=10)
    assert len(items) == 2
    assert items[0]["text"] == "Hello world from RSS"
    assert items[0]["url"] == "https://nitter.example/karpathy/status/1"
    assert items[0]["published_at"] == "2026-05-17T12:00:00+00:00"


def test_parse_rss_strips_html_tags() -> None:
    """Title/summary HTML tag'leri temizlenir."""
    sample = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>&lt;b&gt;Bold&lt;/b&gt; tweet with <em>HTML</em></title>
        <link>https://x.example/1</link>
      </item>
    </channel></rss>"""
    items = _parse_rss(sample, limit=10)
    assert items[0]["text"] == "Bold tweet with HTML"


def test_parse_rss_limit_respected() -> None:
    """5 item RSS feed + limit=3 → 3 item döner."""
    items_xml = "".join(
        f"<item><title>tweet {i}</title><link>https://x.example/{i}</link></item>" for i in range(5)
    )
    sample = f"<rss><channel>{items_xml}</channel></rss>".encode()
    items = _parse_rss(sample, limit=3)
    assert len(items) == 3


# ── fetch_recent_tweets — network mock'lu ───────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_fetch_recent_tweets_first_instance_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """İlk instance 200 dönerse o instance'tan döner; diğerler hiç aranmaz."""
    monkeypatch.setenv("NITTER_INSTANCES", "https://a.example, https://b.example")
    rss = b"""<rss><channel>
      <item><title>tweet from A</title><link>https://x.example/1</link></item>
    </channel></rss>"""
    route_a = respx.get("https://a.example/karpathy/rss").mock(
        return_value=Response(200, content=rss)
    )
    route_b = respx.get("https://b.example/karpathy/rss").mock(
        return_value=Response(200, content=rss)
    )
    items = await fetch_recent_tweets("@karpathy", limit=10)
    assert len(items) == 1
    assert items[0]["text"] == "tweet from A"
    assert route_a.called
    assert not route_b.called  # fallback hiç tetiklenmedi


@pytest.mark.asyncio
@respx.mock
async def test_fetch_recent_tweets_falls_back_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """İlk instance 500 dönerse ikinci instance denenir."""
    monkeypatch.setenv("NITTER_INSTANCES", "https://down.example, https://up.example")
    respx.get("https://down.example/karpathy/rss").mock(return_value=Response(500))
    rss = b"""<rss><channel>
      <item><title>recovered from fallback</title><link>https://x.example/2</link></item>
    </channel></rss>"""
    respx.get("https://up.example/karpathy/rss").mock(return_value=Response(200, content=rss))

    items = await fetch_recent_tweets("karpathy")
    assert len(items) == 1
    assert items[0]["text"] == "recovered from fallback"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_recent_tweets_all_instances_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tüm instance'lar fail → NitterUnavailableError."""
    monkeypatch.setenv("NITTER_INSTANCES", "https://a.example, https://b.example")
    respx.get("https://a.example/karpathy/rss").mock(side_effect=ConnectError("dns"))
    respx.get("https://b.example/karpathy/rss").mock(side_effect=TimeoutException("slow"))

    with pytest.raises(NitterUnavailableError) as exc_info:
        await fetch_recent_tweets("@karpathy")
    assert "All 2 Nitter instances failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_fetch_recent_tweets_empty_handle_returns_empty() -> None:
    """Boş handle network'e gitmeden boş liste döner."""
    items = await fetch_recent_tweets("@")
    assert items == []
    items = await fetch_recent_tweets("")
    assert items == []

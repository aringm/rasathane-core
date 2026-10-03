"""Phase 12-iv: YoutubeChannelIngester tests.

yt-dlp flat-playlist mode mocked; ingester'ın IngestedArticle output'unu
doğrular. Live yt-dlp çağrıları (CI'da slow + flaky) yapılmaz.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ingestion.youtube_channel import (
    YoutubeChannelIngester,
    _cap_words,
    _parse_yt_upload_date,
)


def test_parse_yt_upload_date_valid() -> None:
    assert _parse_yt_upload_date("20260507") == datetime(2026, 5, 7, tzinfo=UTC)


def test_parse_yt_upload_date_none_or_invalid() -> None:
    assert _parse_yt_upload_date(None) is None
    assert _parse_yt_upload_date("") is None
    assert _parse_yt_upload_date("garbage") is None
    assert _parse_yt_upload_date("99999999") is None  # invalid date


def test_cap_words_under_limit() -> None:
    """Limit altındaki metin değişmez."""
    text = "Bu kısa bir test"
    assert _cap_words(text, 10) == text


def test_cap_words_over_limit_appends_ellipsis() -> None:
    text = " ".join(["kelime"] * 250)  # 250 kelime
    out = _cap_words(text, 200)
    assert out is not None
    assert out.endswith("…")
    # 200 kelime + son kelimeye yapışık "…" → 200 token (split boşluğa böler)
    assert len(out.split()) == 200


def test_cap_words_none_returns_none() -> None:
    assert _cap_words(None, 100) is None


@pytest.mark.asyncio
async def test_ingester_returns_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    """yt-dlp video listesi → IngestedArticle batch."""

    async def fake_list(channel_url: str, *, max_count: int) -> list[dict]:
        return [
            {
                "id": "abc123",
                "title": "Karpathy: nanoGPT walk-through",
                "url": "https://www.youtube.com/watch?v=abc123",
                "upload_date": "20260507",
                "duration": 3600,
                "description": "Building nanoGPT from scratch.",
            },
            {
                "id": "def456",
                "title": "Sora 2 deep-dive",
                "url": "https://www.youtube.com/watch?v=def456",
                "upload_date": "20260506",
                "duration": 1800,
                "description": "Examining Sora 2 architecture.",
            },
        ]

    monkeypatch.setattr("ingestion.youtube_channel.list_channel_videos", fake_list)

    ingester = YoutubeChannelIngester()
    articles = await ingester.fetch(
        "https://www.youtube.com/@AndrejKarpathy", metadata={"lang": "en"}
    )

    assert len(articles) == 2
    first = articles[0]
    assert first.title == "Karpathy: nanoGPT walk-through"
    assert first.url == "https://www.youtube.com/watch?v=abc123"
    assert first.published_at == datetime(2026, 5, 7, tzinfo=UTC)
    assert first.metadata["kind"] == "youtube_video"
    assert first.metadata["video_id"] == "abc123"
    assert first.metadata["lang"] == "en"  # source metadata'sı geçti


@pytest.mark.asyncio
async def test_ingester_passes_max_videos_from_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """metadata.max_videos → list_channel_videos.max_count."""
    captured: dict[str, int] = {}

    async def fake_list(channel_url: str, *, max_count: int) -> list[dict]:
        captured["max_count"] = max_count
        return []

    monkeypatch.setattr("ingestion.youtube_channel.list_channel_videos", fake_list)

    ingester = YoutubeChannelIngester()
    await ingester.fetch("https://www.youtube.com/@channel", metadata={"max_videos": 15})

    assert captured["max_count"] == 15


@pytest.mark.asyncio
async def test_ingester_default_max_videos_25(monkeypatch: pytest.MonkeyPatch) -> None:
    """metadata.max_videos yoksa default 25."""
    captured: dict[str, int] = {}

    async def fake_list(channel_url: str, *, max_count: int) -> list[dict]:
        captured["max_count"] = max_count
        return []

    monkeypatch.setattr("ingestion.youtube_channel.list_channel_videos", fake_list)

    ingester = YoutubeChannelIngester()
    await ingester.fetch("https://www.youtube.com/@channel", metadata=None)

    assert captured["max_count"] == 25


@pytest.mark.asyncio
async def test_ingester_caps_summary_at_200_words(monkeypatch: pytest.MonkeyPatch) -> None:
    """FSEK iktibas sınırı: summary max 200 kelime."""
    long_desc = " ".join(["a"] * 250)

    async def fake_list(channel_url: str, *, max_count: int) -> list[dict]:
        return [
            {
                "id": "x",
                "title": "T",
                "url": "https://www.youtube.com/watch?v=x",
                "upload_date": None,
                "duration": 0,
                "description": long_desc,
            }
        ]

    monkeypatch.setattr("ingestion.youtube_channel.list_channel_videos", fake_list)

    ingester = YoutubeChannelIngester()
    articles = await ingester.fetch("https://www.youtube.com/@x", metadata=None)

    assert articles[0].summary is not None
    assert articles[0].summary.endswith("…")
    assert len(articles[0].summary.split()) <= 201


@pytest.mark.asyncio
async def test_ingester_wraps_yt_dlp_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """yt-dlp hata verirse RuntimeError olarak yukarı bubble eder."""

    async def fake_list(channel_url: str, *, max_count: int) -> list[dict]:
        raise OSError("network timeout")

    monkeypatch.setattr("ingestion.youtube_channel.list_channel_videos", fake_list)

    ingester = YoutubeChannelIngester()
    with pytest.raises(RuntimeError, match="yt-dlp channel list failed"):
        await ingester.fetch("https://www.youtube.com/@x", metadata=None)


def test_registry_includes_youtube_channel() -> None:
    """Phase 12-iv: registry'ye yeni type kaydedildi."""
    from ingestion.registry import INGESTER_REGISTRY

    assert "youtube_channel" in INGESTER_REGISTRY
    assert INGESTER_REGISTRY["youtube_channel"].type_name == "youtube_channel"

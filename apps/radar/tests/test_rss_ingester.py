"""RSS ingester unit tests — httpx mocked via respx; no DB required."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import Response
from ingestion.base import IngestedArticle
from ingestion.rss import RssIngester

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FEED_URL = "https://example.com/feed.xml"


@pytest.fixture
def fixture_feed() -> bytes:
    return (FIXTURE_DIR / "sample_feed.xml").read_bytes()


async def test_rss_basic_parse(fixture_feed: bytes) -> None:
    with respx.mock() as mock:
        mock.get(FEED_URL).mock(return_value=Response(200, content=fixture_feed))
        articles = await RssIngester().fetch(FEED_URL)

    assert len(articles) == 3
    assert all(isinstance(a, IngestedArticle) for a in articles)


async def test_rss_url_hash_is_canonical(fixture_feed: bytes) -> None:
    with respx.mock() as mock:
        mock.get(FEED_URL).mock(return_value=Response(200, content=fixture_feed))
        articles = await RssIngester().fetch(FEED_URL)

    for a in articles:
        assert a.url_hash == IngestedArticle.hash_url(a.url)
        assert len(a.url_hash) == 64  # sha256 hex digest


async def test_rss_html_stripped_and_entities_decoded(fixture_feed: bytes) -> None:
    with respx.mock() as mock:
        mock.get(FEED_URL).mock(return_value=Response(200, content=fixture_feed))
        articles = await RssIngester().fetch(FEED_URL)

    first = articles[0]
    assert first.summary is not None
    assert "<p>" not in first.summary
    assert "<b>" not in first.summary
    assert "&amp;" not in first.summary
    assert "Hello world & goodbye" in first.summary


async def test_rss_turkish_chars_preserved(fixture_feed: bytes) -> None:
    with respx.mock() as mock:
        mock.get(FEED_URL).mock(return_value=Response(200, content=fixture_feed))
        articles = await RssIngester().fetch(FEED_URL)

    second = articles[1]
    assert "Türkçe başlık ş ğ ı" in second.title


async def test_rss_summary_capped_at_200_words() -> None:
    long_summary = " ".join(f"word{i}" for i in range(500))
    body = (
        f'<?xml version="1.0"?>'
        f'<rss version="2.0"><channel><title>Long</title>'
        f"<item><title>Long article</title>"
        f"<link>https://example.com/articles/long</link>"
        f"<description>{long_summary}</description></item>"
        f"</channel></rss>"
    ).encode()

    with respx.mock() as mock:
        mock.get(FEED_URL).mock(return_value=Response(200, content=body))
        articles = await RssIngester().fetch(FEED_URL)

    assert len(articles) == 1
    assert articles[0].summary is not None
    word_count = len(articles[0].summary.replace("…", "").split())
    assert word_count <= 200, f"Got {word_count} words; cap is 200"


async def test_rss_skips_items_without_url() -> None:
    body = (
        b'<?xml version="1.0"?>'
        b'<rss version="2.0"><channel><title>Mixed</title>'
        b"<item><title>Has URL</title>"
        b"<link>https://example.com/articles/has-url</link></item>"
        b"<item><title>No URL anywhere</title></item>"
        b"</channel></rss>"
    )

    with respx.mock() as mock:
        mock.get(FEED_URL).mock(return_value=Response(200, content=body))
        articles = await RssIngester().fetch(FEED_URL)

    assert len(articles) == 1
    assert articles[0].title == "Has URL"

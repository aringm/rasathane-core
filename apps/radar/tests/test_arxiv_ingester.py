"""Tests for the ArXiv Atom-API ingester.

We never hit the live ArXiv endpoint here — all HTTP calls go through
``respx`` (already a dev-dep) so the test suite stays hermetic. Atom XML
is delegated to the real ``feedparser`` since we want to exercise the
parser path the production code uses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from ingestion.arxiv import ArxivIngester
from ingestion.base import IngestedArticle

_ARXIV_API = "http://export.arxiv.org/api/query"

# Two-entry minimal Atom payload modelled on a real arxiv response.
_ATOM_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <link href="http://arxiv.org/api/query?search_query=cat:cs.AI" rel="self" type="application/atom+xml"/>
  <title type="html">ArXiv Query</title>
  <id>http://arxiv.org/api/query</id>
  <updated>2026-05-06T00:00:00Z</updated>
  <opensearch:totalResults xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">2</opensearch:totalResults>

  <entry>
    <id>http://arxiv.org/abs/2604.12345v1</id>
    <updated>2026-05-05T12:00:00Z</updated>
    <published>2026-05-05T12:00:00Z</published>
    <title>Self-organising language model agents</title>
    <summary>
      We propose a method for language-model agents to self-organise
      around shared workspaces. Across six benchmarks we observe a 12%
      improvement over single-agent baselines.
    </summary>
    <author><name>Alice Smith</name></author>
    <author><name>Bob Jones</name></author>
    <link href="http://arxiv.org/abs/2604.12345v1" rel="alternate" type="text/html"/>
    <link href="http://arxiv.org/pdf/2604.12345v1" rel="related" type="application/pdf" title="pdf"/>
    <arxiv:primary_category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
  </entry>

  <entry>
    <id>http://arxiv.org/abs/2604.99999</id>
    <updated>2026-05-04T08:30:00Z</updated>
    <published>2026-05-04T08:30:00Z</published>
    <title>A Türkçe titled paper with özel karakterler</title>
    <summary>Kısa özet.</summary>
    <author><name>Solo Author</name></author>
    <link href="http://arxiv.org/abs/2604.99999" rel="alternate" type="text/html"/>
    <arxiv:primary_category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""


def _query_url(category: str = "cs.AI") -> str:
    return (
        f"{_ARXIV_API}?search_query=cat:{category}"
        "&sortBy=submittedDate&sortOrder=descending&max_results=20"
    )


@pytest.mark.asyncio
async def test_fetch_returns_articles_with_arxiv_metadata() -> None:
    url = _query_url("cs.AI")
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=_ATOM_FIXTURE.encode()))

        ingester = ArxivIngester()
        articles = await ingester.fetch(url)

    assert len(articles) == 2

    first = articles[0]
    assert first.title == "Self-organising language model agents"
    assert first.url == "http://arxiv.org/abs/2604.12345v1"
    assert first.url_hash == IngestedArticle.hash_url("http://arxiv.org/abs/2604.12345v1")
    assert first.author == "Alice Smith, Bob Jones"
    assert first.published_at == datetime(2026, 5, 5, 12, 0, 0, tzinfo=UTC)
    assert "12% improvement" in (first.summary or "")
    assert first.metadata["arxiv_id"] == "2604.12345"
    assert first.metadata["arxiv_primary_category"] == "cs.AI"
    assert set(first.metadata["arxiv_categories"]) == {"cs.AI", "cs.LG"}
    assert first.metadata["pdf_url"] == "http://arxiv.org/pdf/2604.12345v1"
    assert first.metadata["source_kind"] == "arxiv"
    assert first.metadata["feed_url"] == url

    second = articles[1]
    assert "özel karakterler" in second.title  # Türkçe survives parse
    assert second.author == "Solo Author"
    assert second.metadata["arxiv_id"] == "2604.99999"
    assert second.metadata["arxiv_primary_category"] == "cs.CL"
    assert "pdf_url" not in second.metadata  # entry has no pdf link


@pytest.mark.asyncio
async def test_fetch_acquires_rate_limiter_when_provided() -> None:
    url = _query_url("cs.LG")
    acquired_keys: list[str] = []

    class _RecordingLimiter:
        async def acquire(self, key: str) -> None:
            acquired_keys.append(key)

    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=_ATOM_FIXTURE.encode()))

        ingester = ArxivIngester(rate_limiter=_RecordingLimiter())  # type: ignore[arg-type]
        await ingester.fetch(url)

    assert acquired_keys == ["arxiv"]


@pytest.mark.asyncio
async def test_fetch_caps_summary_at_200_words() -> None:
    long_words = " ".join(f"word{i}" for i in range(500))
    payload = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2604.55555v1</id>
    <published>2026-05-01T00:00:00Z</published>
    <title>Long abstract paper</title>
    <summary>{long_words}</summary>
    <link href="http://arxiv.org/abs/2604.55555v1" rel="alternate" type="text/html"/>
  </entry>
</feed>
"""

    url = _query_url("cs.AI")
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=payload.encode()))
        articles = await ArxivIngester().fetch(url)

    assert len(articles) == 1
    summary = articles[0].summary or ""
    # Capped to first 200 words; ellipsis is glued to the last word with no
    # space, so split() still yields 200 tokens.
    assert summary.endswith("…")
    assert len(summary.split()) == 200
    assert "word199" in summary
    assert "word200" not in summary


@pytest.mark.asyncio
async def test_fetch_skips_entries_with_no_url() -> None:
    payload = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Phantom paper</title>
    <summary>No id, no link, nothing.</summary>
  </entry>
</feed>
"""
    url = _query_url("cs.AI")
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=payload.encode()))
        articles = await ArxivIngester().fetch(url)

    assert articles == []


@pytest.mark.asyncio
async def test_fetch_raises_when_atom_is_unparseable() -> None:
    """An empty body produces no entries and a bozo flag → fatal."""
    url = _query_url("cs.AI")
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=b"not xml at all"))
        with pytest.raises(RuntimeError, match="feedparser failed"):
            await ArxivIngester().fetch(url)


@pytest.mark.asyncio
async def test_fetch_raises_on_http_5xx() -> None:
    url = _query_url("cs.AI")
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(503, content=b""))
        with pytest.raises(httpx.HTTPStatusError):
            await ArxivIngester().fetch(url)


@pytest.mark.asyncio
async def test_metadata_kwarg_merges_into_entry_metadata() -> None:
    url = _query_url("cs.AI")
    with respx.mock(assert_all_called=True) as router:
        router.get(url).mock(return_value=httpx.Response(200, content=_ATOM_FIXTURE.encode()))
        articles = await ArxivIngester().fetch(
            url,
            metadata={"lang": "en", "feed_url": "should-be-overridden"},
        )

    # User metadata wins over the synthetic feed_url we inject.
    assert articles[0].metadata["lang"] == "en"
    assert articles[0].metadata["feed_url"] == "should-be-overridden"
    # Arxiv enrichment still present.
    assert articles[0].metadata["arxiv_id"] == "2604.12345"


def test_extract_arxiv_id_handles_versioned_and_legacy_urls() -> None:
    from ingestion.arxiv import _extract_arxiv_id

    assert _extract_arxiv_id("http://arxiv.org/abs/2604.12345v1") == "2604.12345"
    assert _extract_arxiv_id("http://arxiv.org/abs/2604.12345") == "2604.12345"
    assert _extract_arxiv_id("http://arxiv.org/pdf/2604.12345v3") == "2604.12345"
    assert _extract_arxiv_id("http://arxiv.org/abs/cs.CL/0102015") == "cs.CL/0102015"
    assert _extract_arxiv_id("https://example.com/random") is None
    assert _extract_arxiv_id("") is None


def test_feeds_yaml_rejects_unknown_type() -> None:
    """Phase 8A locked feeds.yaml ``type`` to a Literal."""
    from ingestion.feeds_yaml import FeedYamlEntry
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FeedYamlEntry(
            name="Bogus",
            category="dunya_ai",
            type="bogus",  # type: ignore[arg-type]
            url="https://example.com",
        )


def test_feeds_yaml_rejects_unknown_category() -> None:
    from ingestion.feeds_yaml import FeedYamlEntry
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FeedYamlEntry(
            name="Bogus",
            category="bogus_cat",  # type: ignore[arg-type]
            type="rss",
            url="https://example.com",
        )


def test_registry_passes_rate_limiter_to_arxiv() -> None:
    from ingestion.registry import get_ingester

    sentinel: Any = object()
    ingester = get_ingester("arxiv", rate_limiter=sentinel)
    assert isinstance(ingester, ArxivIngester)
    assert ingester._rate_limiter is sentinel


def test_registry_unknown_type_raises() -> None:
    from ingestion.registry import get_ingester

    with pytest.raises(ValueError, match="No ingester registered"):
        get_ingester("ghostfeed")

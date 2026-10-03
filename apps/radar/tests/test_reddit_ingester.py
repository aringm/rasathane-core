"""Tests for ``ingestion.reddit.RedditIngester``.

We never hit reddit.com here — respx fakes the JSON. Reddit's response
shape is well-documented and stable, so a hand-built fixture suffices.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from ingestion.base import IngestedArticle
from ingestion.reddit import LINKPOST_PLACEHOLDER, RedditIngester


def _reddit_post(
    *,
    post_id: str = "abc123",
    title: str = "Sample post",
    selftext: str = "",
    author: str = "alice",
    created_utc: float = 1714992000.0,  # 2024-05-06 10:40:00 UTC
    score: int = 42,
    num_comments: int = 7,
    is_self: bool = True,
    external_url: str | None = None,
    flair: str | None = None,
    subreddit: str = "MachineLearning",
    permalink: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "t3",
        "data": {
            "id": post_id,
            "title": title,
            "selftext": selftext,
            "author": author,
            "created_utc": created_utc,
            "score": score,
            "num_comments": num_comments,
            "is_self": is_self,
            "url": external_url or f"https://www.reddit.com/r/{subreddit}/comments/{post_id}/",
            "permalink": permalink or f"/r/{subreddit}/comments/{post_id}/sample_post/",
            "subreddit": subreddit,
            "link_flair_text": flair,
        },
    }


def _listing(children: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": {"after": None, "children": children}}


_SOURCE_URL = "https://www.reddit.com/r/MachineLearning/top.json?t=day&limit=15"


@pytest.mark.asyncio
async def test_fetch_parses_self_post() -> None:
    payload = _listing(
        [
            _reddit_post(
                post_id="abc",
                title="What's the SOTA for Türkçe NER?",
                selftext="I've been working on legal NER for Turkish texts...",
                author="legal_ml_dev",
                created_utc=1714992000.0,
                score=88,
                num_comments=12,
                is_self=True,
                flair="Discussion",
            )
        ]
    )

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(_SOURCE_URL)

    assert len(articles) == 1
    article = articles[0]

    assert article.title == "What's the SOTA for Türkçe NER?"
    assert article.url == "https://www.reddit.com/r/MachineLearning/comments/abc/sample_post/"
    assert article.url_hash == IngestedArticle.hash_url(article.url)
    assert article.author == "legal_ml_dev"
    assert article.published_at == datetime(2024, 5, 6, 10, 40, 0, tzinfo=UTC)
    assert article.summary is not None
    assert "legal NER" in article.summary

    meta = article.metadata
    assert meta["source_kind"] == "reddit"
    assert meta["subreddit"] == "MachineLearning"
    assert meta["score"] == 88
    assert meta["num_comments"] == 12
    assert meta["is_self"] is True
    assert meta["reddit_id"] == "abc"
    assert meta["flair"] == "Discussion"
    assert "external_url" not in meta  # selfposts don't carry one


@pytest.mark.asyncio
async def test_fetch_parses_link_post() -> None:
    payload = _listing(
        [
            _reddit_post(
                post_id="lp1",
                title="Anthropic releases Claude 4.7",
                selftext="",  # linkposts have no selftext
                is_self=False,
                external_url="https://www.anthropic.com/news/claude-4-7",
            )
        ]
    )

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(_SOURCE_URL)

    article = articles[0]
    assert article.summary == LINKPOST_PLACEHOLDER
    assert article.metadata["external_url"] == "https://www.anthropic.com/news/claude-4-7"
    assert article.metadata["is_self"] is False


@pytest.mark.asyncio
async def test_fetch_skips_non_t3_kinds() -> None:
    """Reddit listings can occasionally include t1 (comments), t5 (subreddit
    metadata) when they're embedded in unusual contexts. We only want t3."""
    payload = _listing(
        [
            {"kind": "t1", "data": {"body": "a comment"}},
            _reddit_post(post_id="real"),
            {"kind": "t5", "data": {"display_name": "subreddit-meta"}},
        ]
    )

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(_SOURCE_URL)

    assert len(articles) == 1
    assert articles[0].metadata["reddit_id"] == "real"


@pytest.mark.asyncio
async def test_fetch_skips_entries_with_no_permalink() -> None:
    payload = _listing(
        [
            {
                "kind": "t3",
                "data": {
                    "id": "ghost",
                    "title": "No permalink",
                    "selftext": "x",
                    "author": "x",
                    "created_utc": 1714992000.0,
                    # permalink missing
                },
            }
        ]
    )

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(_SOURCE_URL)

    assert articles == []


@pytest.mark.asyncio
async def test_fetch_caps_summary_at_200_words() -> None:
    long_text = " ".join(f"w{i}" for i in range(500))
    payload = _listing([_reddit_post(post_id="long", selftext=long_text, is_self=True)])

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(_SOURCE_URL)

    summary = articles[0].summary or ""
    assert summary.endswith("…")
    assert len(summary.split()) == 200
    assert "w199" in summary
    assert "w200" not in summary


@pytest.mark.asyncio
async def test_fetch_handles_deleted_author() -> None:
    """Reddit reports ``[deleted]`` for removed users; we keep it as the
    author string rather than nulling it out — preserves the historical
    fact that *someone* posted, even if they've since deleted."""
    payload = _listing([_reddit_post(post_id="d", author="[deleted]")])

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(_SOURCE_URL)

    assert articles[0].author == "[deleted]"


@pytest.mark.asyncio
async def test_fetch_acquires_rate_limiter_when_provided() -> None:
    payload = _listing([_reddit_post()])
    acquired_keys: list[str] = []

    class _RecordingLimiter:
        async def acquire(self, key: str) -> None:
            acquired_keys.append(key)

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        ingester = RedditIngester(rate_limiter=_RecordingLimiter())  # type: ignore[arg-type]
        await ingester.fetch(_SOURCE_URL)

    assert acquired_keys == ["reddit"]


@pytest.mark.asyncio
async def test_fetch_sends_unique_user_agent() -> None:
    """Reddit 429s default UAs; verify our identifier is set on the wire."""
    payload = _listing([_reddit_post()])
    captured_uas: list[str] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured_uas.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json=payload)

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(side_effect=capture)
        await RedditIngester().fetch(_SOURCE_URL)

    assert len(captured_uas) == 1
    ua = captured_uas[0]
    assert "rasathane" in ua
    assert "/u/" in ua  # Reddit asks for /u/<owner> in the UA


@pytest.mark.asyncio
async def test_fetch_raises_on_unexpected_shape() -> None:
    payload: dict[str, Any] = {"data": {"children": "not-a-list"}}

    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        with pytest.raises(RuntimeError, match="not a list"):
            await RedditIngester().fetch(_SOURCE_URL)


@pytest.mark.asyncio
async def test_fetch_raises_on_http_error() -> None:
    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(429, text=""))
        with pytest.raises(httpx.HTTPStatusError):
            await RedditIngester().fetch(_SOURCE_URL)


@pytest.mark.asyncio
async def test_metadata_kwarg_merges_into_entry_metadata() -> None:
    payload = _listing([_reddit_post()])
    with respx.mock(assert_all_called=True) as router:
        router.get(_SOURCE_URL).mock(return_value=httpx.Response(200, json=payload))
        articles = await RedditIngester().fetch(
            _SOURCE_URL,
            metadata={"lang": "en", "subreddit": "should-be-overridden"},
        )

    # User metadata wins where keys collide.
    assert articles[0].metadata["lang"] == "en"
    assert articles[0].metadata["subreddit"] == "should-be-overridden"
    # Reddit enrichment unaffected on non-colliding keys.
    assert articles[0].metadata["score"] == 42


def test_registry_returns_reddit_ingester() -> None:
    from ingestion.registry import get_ingester

    ingester = get_ingester("reddit")
    assert isinstance(ingester, RedditIngester)


def test_feeds_yaml_accepts_reddit_type() -> None:
    """Phase 8B-i added "reddit" to the SourceType Literal."""
    from ingestion.feeds_yaml import FeedYamlEntry

    entry = FeedYamlEntry(
        name="r/test",
        category="legaltech",
        type="reddit",
        url="https://www.reddit.com/r/test/new.json",
    )
    assert entry.type == "reddit"

"""Phase 35-xviii: GitHub trending discovery tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingestion.github_trending import (
    DEFAULT_QUERIES,
    _build_query_url,
    fetch_trending_feeds,
    fetch_trending_query,
    parse_search_results,
)

SAMPLE_SEARCH_RESPONSE = {
    "total_count": 2,
    "incomplete_results": False,
    "items": [
        {
            "id": 1,
            "full_name": "deepseek-ai/DeepSeek-V4",
            "html_url": "https://github.com/deepseek-ai/DeepSeek-V4",
            "description": "Next-gen MoE model from DeepSeek",
            "stargazers_count": 25000,
            "language": "Python",
            "pushed_at": "2026-05-20T18:00:00Z",
            "topics": ["llm", "moe", "deep-learning"],
        },
        {
            "id": 2,
            "full_name": "anthropic/courses",
            "html_url": "https://github.com/anthropic/courses",
            "description": "Anthropic training course materials",
            "stargazers_count": 12000,
            "language": "Jupyter Notebook",
            "pushed_at": "2026-05-19T14:30:00Z",
            "topics": ["llm", "education"],
        },
    ],
}


def test_parse_search_results_extracts_posts() -> None:
    posts = parse_search_results(
        SAMPLE_SEARCH_RESPONSE, query_name="llm", tags=["dunya_ai"]
    )
    assert len(posts) == 2
    p = posts[0]
    assert p["title"] == "deepseek-ai/DeepSeek-V4"
    assert p["url"] == "https://github.com/deepseek-ai/DeepSeek-V4"
    assert p["handle"] == "deepseek-ai/DeepSeek-V4"
    assert p["platform"] == "github"
    assert p["posted_at"] == "2026-05-20T18:00:00Z"
    assert p["tags"] == ["dunya_ai"]
    # _meta starts/lang/query bilgisi
    assert p["_meta"]["stars"] == 25000
    assert p["_meta"]["language"] == "Python"
    assert p["_meta"]["query"] == "llm"


def test_parse_search_results_text_includes_stars_and_language() -> None:
    """Text özetinde stars + language görünür."""
    posts = parse_search_results(SAMPLE_SEARCH_RESPONSE, query_name="llm", tags=[])
    assert "25000" in posts[0]["text"]
    assert "Python" in posts[0]["text"]


def test_parse_search_results_empty_items_returns_empty() -> None:
    """API 'no results' → boş list."""
    posts = parse_search_results({"items": []}, query_name="x", tags=[])
    assert posts == []


def test_parse_search_results_missing_items_returns_empty() -> None:
    """Bozuk response (items field yok) → boş list."""
    posts = parse_search_results({}, query_name="x", tags=[])
    assert posts == []


def test_build_query_url_includes_filters() -> None:
    """URL builder topic + stars + pushed_at + sort params barındırır."""
    url = _build_query_url(topic="llm", min_stars=500, pushed_days_ago=7)
    assert "topic%3Allm" in url  # URL-encoded `topic:llm`
    assert "stars%3A%3E%3D500" in url  # `stars:>=500`
    assert "pushed%3A%3E%3D" in url  # `pushed:>=`
    assert "sort=stars" in url
    assert "order=desc" in url


def test_default_queries_includes_user_interest_areas() -> None:
    """Phase 35-xviii başlangıç: llm + ai-agents + open-source + legaltech + turkish-nlp."""
    expected = {"llm", "ai-agents", "open-source-llm", "legaltech", "turkish-nlp"}
    assert set(DEFAULT_QUERIES.keys()) == expected
    # Tag mapping
    assert "dunya_ai" in DEFAULT_QUERIES["llm"]["tags"]
    assert "legaltech" in DEFAULT_QUERIES["legaltech"]["tags"]
    assert "turkiye_ai" in DEFAULT_QUERIES["turkish-nlp"]["tags"]


@pytest.mark.asyncio
async def test_fetch_trending_query_uses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_file = cache_root / "github_trending_llm.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "query": "llm",
                "platform": "github",
                "posts": [
                    {
                        "title": "cached/repo",
                        "url": "https://x",
                        "handle": "cached/repo",
                        "platform": "github",
                        "posted_at": "2026-05-20T10:00:00Z",
                        "tags": ["dunya_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    async def fail_fetch(*_a, **_k):
        raise AssertionError("Cache fresh — HTTP fetch should not run")

    monkeypatch.setattr("ingestion.github_trending._http_search", fail_fetch)
    posts = await fetch_trending_query(
        "llm",
        {"topic": "llm", "min_stars": 500, "tags": ["dunya_ai"]},
        cache_root=cache_root,
        cache_ttl_sec=3600,
    )
    assert posts[0]["title"] == "cached/repo"


@pytest.mark.asyncio
async def test_fetch_trending_query_writes_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"

    async def fake_search(_url):
        return SAMPLE_SEARCH_RESPONSE

    monkeypatch.setattr("ingestion.github_trending._http_search", fake_search)
    posts = await fetch_trending_query(
        "llm",
        {"topic": "llm", "min_stars": 500, "tags": ["dunya_ai"]},
        cache_root=cache_root,
    )
    assert len(posts) == 2
    assert (cache_root / "github_trending_llm.json").is_file()


@pytest.mark.asyncio
async def test_fetch_trending_feeds_parallel_aggregates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"

    async def fake_search(_url):
        return SAMPLE_SEARCH_RESPONSE

    monkeypatch.setattr("ingestion.github_trending._http_search", fake_search)
    queries = {
        "llm": {"topic": "llm", "min_stars": 500, "tags": ["dunya_ai"]},
        "legaltech": {"topic": "legaltech", "min_stars": 30, "tags": ["legaltech"]},
    }
    posts = await fetch_trending_feeds(queries, cache_root=cache_root)
    # 2 query × 2 post = 4
    assert len(posts) == 4
    # Time-sorted DESC
    assert posts[0]["posted_at"] == "2026-05-20T18:00:00Z"

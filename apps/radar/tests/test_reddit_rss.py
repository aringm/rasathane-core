"""Phase 35-xxi: Reddit OAuth adapter tests (Phase 35-xvi RSS testlerinden rewrite)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx
from httpx import Response
from ingestion.reddit_rss import (
    _TOKEN_CACHE,
    DEFAULT_SUBREDDITS,
    fetch_reddit_feeds,
    fetch_subreddit,
    parse_reddit_listing,
)

# Reddit JSON listing — gerçek `oauth.reddit.com/r/X/hot.json` response yapısı.
SAMPLE_LISTING = {
    "kind": "Listing",
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "abc123",
                    "title": "[D] Anthropic Claude 4.7 paper review",
                    "permalink": "/r/MachineLearning/comments/abc123/",
                    "author": "researcher_42",
                    "created_utc": 1747765800,  # 2025-05-20T15:50:00Z
                    "selftext": "Just read the technical report on Claude 4.7...",
                    "score": 250,
                    "num_comments": 42,
                    "subreddit": "MachineLearning",
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "def456",
                    "title": "[N] DeepSeek-V4 announced",
                    "permalink": "/r/MachineLearning/comments/def456/",
                    "author": "ai_news_bot",
                    "created_utc": 1747752000,  # 2025-05-20T12:00:00Z
                    "selftext": "DeepSeek announced their next model...",
                    "score": 180,
                    "num_comments": 30,
                    "subreddit": "MachineLearning",
                },
            },
            {
                "kind": "t1",  # Comment, atlanmalı
                "data": {"body": "irrelevant comment"},
            },
        ]
    },
}


@pytest.fixture(autouse=True)
def _reset_token_cache():
    """Her test fresh token state — module-level cache test'leri etkilemesin."""
    _TOKEN_CACHE["token"] = None
    _TOKEN_CACHE["expires_at"] = 0.0
    yield


@pytest.fixture
def reddit_env(monkeypatch: pytest.MonkeyPatch):
    """Test için Reddit OAuth env vars."""
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test_client_id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test_client_secret")
    monkeypatch.setenv("REDDIT_USER_AGENT", "rasathane-test/1.0")


def test_parse_reddit_listing_extracts_posts() -> None:
    posts = parse_reddit_listing(
        SAMPLE_LISTING, subreddit="MachineLearning", tags=["dunya_ai"]
    )
    # 2 t3 + 1 t1 (comment, atlanır) → 2 post
    assert len(posts) == 2
    p = posts[0]
    assert p["title"] == "[D] Anthropic Claude 4.7 paper review"
    assert p["url"] == "https://www.reddit.com/r/MachineLearning/comments/abc123/"
    assert p["handle"] == "r/MachineLearning"
    assert p["platform"] == "reddit"
    assert p["author"] == "researcher_42"
    assert p["tags"] == ["dunya_ai"]
    # Bonus meta (score, num_comments) — UI ileride kullanır
    assert p["_meta"]["score"] == 250
    assert p["_meta"]["num_comments"] == 42


def test_parse_reddit_listing_converts_created_utc_to_iso() -> None:
    """Unix timestamp → ISO 8601 UTC Z-suffix."""
    posts = parse_reddit_listing(SAMPLE_LISTING, subreddit="x", tags=[])
    # 1747765800 Unix = 2025-05-20T18:30:00Z (datetime.fromtimestamp UTC)
    assert posts[0]["posted_at"] == "2025-05-20T18:30:00Z"
    # İkinci post 13800 sec önce (4 saat fark)
    assert posts[1]["posted_at"] == "2025-05-20T14:40:00Z"


def test_parse_reddit_listing_skips_comments() -> None:
    """`kind: t1` (comment) atlanır — sadece t3 (submission) post olur."""
    posts = parse_reddit_listing(SAMPLE_LISTING, subreddit="x", tags=[])
    # Sample'da 1 t1 var, hiçbir post'ta "irrelevant comment" olmamalı
    assert all("irrelevant" not in p.get("text", "") for p in posts)


def test_parse_reddit_listing_empty_data_returns_empty() -> None:
    """`data.children` boş → boş list (defensive)."""
    assert parse_reddit_listing({"data": {"children": []}}, subreddit="x", tags=[]) == []
    assert parse_reddit_listing({}, subreddit="x", tags=[]) == []


def test_default_subreddits_preserved_from_phase_35_xvi() -> None:
    """Phase 35-xxi OAuth migrate'inde subreddit listesi korunur."""
    expected = {
        "MachineLearning",
        "LocalLLaMA",
        "artificial",
        "LegalTechnology",
        "lawyertalk",
        "Turkey",
        "Turkiye",
    }
    assert set(DEFAULT_SUBREDDITS.keys()) == expected


@pytest.mark.asyncio
async def test_fetch_subreddit_oauth_flow(
    tmp_path: Path, reddit_env: None
) -> None:
    """OAuth flow: token endpoint → listing endpoint → cache yazılır."""
    cache_root = tmp_path / "cache"
    with respx.mock() as router:
        router.post("https://www.reddit.com/api/v1/access_token").mock(
            return_value=Response(
                200,
                json={
                    "access_token": "fake_bearer_token",
                    "token_type": "bearer",
                    "expires_in": 3600,
                    "scope": "*",
                },
            )
        )
        router.get(
            "https://oauth.reddit.com/r/MachineLearning/hot",
            params={"limit": 25},
        ).mock(return_value=Response(200, json=SAMPLE_LISTING))

        posts = await fetch_subreddit(
            "MachineLearning",
            ["dunya_ai"],
            cache_root=cache_root,
        )

    assert len(posts) == 2
    assert posts[0]["title"].startswith("[D] Anthropic")
    # Cache yazıldı mı?
    cache_file = cache_root / "reddit_MachineLearning.json"
    assert cache_file.is_file()
    cached = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cached["subreddit"] == "MachineLearning"


@pytest.mark.asyncio
async def test_fetch_subreddit_uses_cache_when_fresh(
    tmp_path: Path, reddit_env: None
) -> None:
    """Fresh cache → OAuth endpoint hiç çağrılmaz."""
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_file = cache_root / "reddit_MachineLearning.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "subreddit": "MachineLearning",
                "platform": "reddit",
                "posts": [
                    {
                        "title": "cached post",
                        "url": "https://x",
                        "handle": "r/MachineLearning",
                        "platform": "reddit",
                        "posted_at": "2026-05-20T10:00:00Z",
                        "tags": ["dunya_ai"],
                        "safe": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    # respx mock olmadan — fresh cache HTTP isteğine düşmez (eğer düşerse error)
    posts = await fetch_subreddit(
        "MachineLearning",
        ["dunya_ai"],
        cache_root=cache_root,
        cache_ttl_sec=3600,
    )
    assert posts[0]["title"] == "cached post"


@pytest.mark.asyncio
async def test_fetch_subreddit_missing_credentials_returns_stale_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Env vars yoksa: stale cache döner, RuntimeError yutulur (fail-soft)."""
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("REDDIT_USER_AGENT", raising=False)
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    # Stale cache (1 yıl önce, normalde refresh ister)
    old = (datetime.now(UTC).replace(year=datetime.now(UTC).year - 1)).isoformat()
    (cache_root / "reddit_MachineLearning.json").write_text(
        json.dumps(
            {
                "fetched_at": old,
                "subreddit": "MachineLearning",
                "platform": "reddit",
                "posts": [{"title": "stale cached", "url": "https://x"}],
            }
        ),
        encoding="utf-8",
    )
    posts = await fetch_subreddit("MachineLearning", [], cache_root=cache_root)
    # Fail-soft: stale cache'i döndürür
    assert posts[0]["title"] == "stale cached"


@pytest.mark.asyncio
async def test_fetch_reddit_feeds_parallel_token_reuse(
    tmp_path: Path, reddit_env: None
) -> None:
    """Birden çok subreddit paralel fetch → 1 token request, N listing request."""
    cache_root = tmp_path / "cache"
    token_calls = 0

    def _token_callback(_request):
        nonlocal token_calls
        token_calls += 1
        return Response(
            200,
            json={"access_token": "shared_token", "expires_in": 3600},
        )

    with respx.mock() as router:
        router.post(
            "https://www.reddit.com/api/v1/access_token"
        ).mock(side_effect=_token_callback)
        # Tüm subreddit'ler için generic listing mock
        router.get(url__regex=r"https://oauth\.reddit\.com/r/.+/hot").mock(
            return_value=Response(200, json=SAMPLE_LISTING)
        )

        subs = {
            "MachineLearning": ["dunya_ai"],
            "LocalLLaMA": ["acik_kaynak_ai"],
        }
        posts = await fetch_reddit_feeds(subs, cache_root=cache_root)

    # 2 subreddit × 2 post = 4
    assert len(posts) == 4
    # Token tek seferde alındı (cache reuse)
    assert token_calls == 1, f"Expected 1 token call, got {token_calls}"

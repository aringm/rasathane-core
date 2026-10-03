"""Phase 35-xvii: Medium RSS adapter tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from ingestion.medium_rss import (
    DEFAULT_PUBLICATIONS,
    _parse_pubdate,
    fetch_medium_feeds,
    fetch_publication,
    parse_medium_feed,
)

# Medium RSS 2.0 — gerçek feed örneğinden simplified sample.
# RFC 822 `<pubDate>` formatı (lexicographic compare çalışmaz; ISO 8601'e
# çevrilmeli — Phase 35-xv time filter gereği).
SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <channel>
        <title>Towards Data Science</title>
        <link>https://medium.com/towards-data-science</link>
        <item>
            <title>The State of Reasoning Models in 2026</title>
            <link>https://medium.com/towards-data-science/reasoning-2026-abc123</link>
            <pubDate>Wed, 20 May 2026 15:30:00 GMT</pubDate>
            <dc:creator>Sebastian Raschka</dc:creator>
            <description>Long-form analysis of o3, Claude 4.7, DeepSeek-R2...</description>
        </item>
        <item>
            <title>Fine-tuning Llama 4 on a Single GPU</title>
            <link>https://medium.com/towards-data-science/llama4-finetune-def456</link>
            <pubDate>Mon, 18 May 2026 09:15:00 GMT</pubDate>
            <dc:creator>Jane Doe</dc:creator>
            <description>QLoRA + gradient checkpointing pattern...</description>
        </item>
    </channel>
</rss>"""


def test_parse_pubdate_rfc822_to_iso() -> None:
    """RFC 822 `Wed, 20 May 2026 15:30:00 GMT` → ISO 8601 UTC Z-suffix."""
    iso = _parse_pubdate("Wed, 20 May 2026 15:30:00 GMT")
    assert iso == "2026-05-20T15:30:00Z"


def test_parse_pubdate_empty_returns_none() -> None:
    assert _parse_pubdate("") is None


def test_parse_pubdate_malformed_returns_none() -> None:
    assert _parse_pubdate("not a date") is None


def test_parse_medium_feed_extracts_posts() -> None:
    posts = parse_medium_feed(
        SAMPLE_RSS, publication="towards-data-science", tags=["dunya_ai"]
    )
    assert len(posts) == 2
    p = posts[0]
    assert p["title"] == "The State of Reasoning Models in 2026"
    assert p["url"] == "https://medium.com/towards-data-science/reasoning-2026-abc123"
    assert p["handle"] == "medium.com/towards-data-science"
    assert p["platform"] == "medium"
    assert p["posted_at"] == "2026-05-20T15:30:00Z"
    assert p["author"] == "Sebastian Raschka"
    assert p["tags"] == ["dunya_ai"]


def test_parse_medium_feed_dc_creator_for_author() -> None:
    """Medium author = Dublin Core `<dc:creator>` namespace tag."""
    posts = parse_medium_feed(SAMPLE_RSS, publication="x", tags=[])
    assert posts[0]["author"] == "Sebastian Raschka"
    assert posts[1]["author"] == "Jane Doe"


def test_parse_medium_feed_malformed_xml_returns_empty() -> None:
    posts = parse_medium_feed("<bad xml", publication="x", tags=[])
    assert posts == []


def test_parse_medium_feed_no_channel_returns_empty() -> None:
    """RSS root'ta `<channel>` yoksa boş list (defensive)."""
    posts = parse_medium_feed(
        "<?xml version='1.0'?><rss><nope/></rss>",
        publication="x",
        tags=[],
    )
    assert posts == []


def test_default_publications_includes_curated_set() -> None:
    """Phase 35-xvii başlangıç: TDS + Better Programming."""
    assert "towards-data-science" in DEFAULT_PUBLICATIONS
    assert "better-programming" in DEFAULT_PUBLICATIONS
    assert DEFAULT_PUBLICATIONS["towards-data-science"] == ["dunya_ai"]


@pytest.mark.asyncio
async def test_fetch_publication_uses_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    cache_file = cache_root / "medium_towards-data-science.json"
    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "publication": "towards-data-science",
                "platform": "medium",
                "posts": [
                    {
                        "title": "cached medium post",
                        "url": "https://x",
                        "handle": "medium.com/towards-data-science",
                        "platform": "medium",
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

    monkeypatch.setattr("ingestion.medium_rss._http_get_rss", fail_fetch)
    posts = await fetch_publication(
        "towards-data-science",
        ["dunya_ai"],
        cache_root=cache_root,
        cache_ttl_sec=3600,
    )
    assert posts[0]["title"] == "cached medium post"


@pytest.mark.asyncio
async def test_fetch_publication_writes_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"

    async def fake_fetch(_url):
        return SAMPLE_RSS

    monkeypatch.setattr("ingestion.medium_rss._http_get_rss", fake_fetch)
    posts = await fetch_publication(
        "towards-data-science", ["dunya_ai"], cache_root=cache_root
    )
    assert len(posts) == 2
    assert (cache_root / "medium_towards-data-science.json").is_file()


@pytest.mark.asyncio
async def test_fetch_medium_feeds_parallel_aggregates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"

    async def fake_fetch(_url):
        return SAMPLE_RSS

    monkeypatch.setattr("ingestion.medium_rss._http_get_rss", fake_fetch)
    pubs = {
        "towards-data-science": ["dunya_ai"],
        "better-programming": ["dunya_ai"],
    }
    posts = await fetch_medium_feeds(pubs, cache_root=cache_root)
    # 2 pub × 2 post = 4
    assert len(posts) == 4
    # Time-sorted DESC: 2026-05-20 15:30 önce
    assert posts[0]["posted_at"] == "2026-05-20T15:30:00Z"

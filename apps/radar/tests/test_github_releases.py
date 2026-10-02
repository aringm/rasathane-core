"""Phase 33-ii: GitHub releases.atom feed adapter tests."""

from datetime import UTC, datetime

import pytest
from ingestion.github_releases import fetch_github_releases, parse_atom

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>tag:github.com,2008:https://github.com/deepseek-ai/DeepSeek-V3/releases</id>
  <title>Release notes from DeepSeek-V3</title>
  <entry>
    <id>tag:github.com,2008:Repository/.../v0.4.2</id>
    <updated>2026-05-19T14:23:00Z</updated>
    <title>v0.4.2: MoE optimizations</title>
    <link rel="alternate" type="text/html" href="https://github.com/deepseek-ai/DeepSeek-V3/releases/tag/v0.4.2"/>
    <author><name>deepseek-bot</name></author>
    <content type="html">MoE quantization improvements</content>
  </entry>
</feed>"""


def test_parse_atom_extracts_releases():
    items = parse_atom(SAMPLE_ATOM, handle="deepseek-ai/DeepSeek-V3")
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "v0.4.2: MoE optimizations"
    assert item["url"] == "https://github.com/deepseek-ai/DeepSeek-V3/releases/tag/v0.4.2"
    assert item["handle"] == "deepseek-ai/DeepSeek-V3"
    assert item["platform"] == "github"
    assert "acik_kaynak_ai" in item["tags"]


def test_parse_atom_empty_feed():
    empty = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    items = parse_atom(empty, handle="x/y")
    assert items == []


@pytest.mark.asyncio
async def test_fetch_github_releases_uses_cache(tmp_path, monkeypatch):
    """Cache fresh ise HTTP fetch yapmaz."""
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    handle = "deepseek-ai/DeepSeek-V3"
    safe_handle = handle.replace("/", "_")
    cache_file = cache_root / f"github_{safe_handle}.json"

    import json

    cache_file.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "posts": [
                    {
                        "title": "cached",
                        "url": "https://x",
                        "handle": handle,
                        "platform": "github",
                        "posted_at": "2026-05-19T00:00:00+00:00",
                        "tags": ["acik_kaynak_ai"],
                        "safe": True,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    async def fail_fetch(*_a, **_k):
        raise AssertionError("Should not be called when cache is fresh")

    monkeypatch.setattr("ingestion.github_releases._http_get_atom", fail_fetch)
    posts = await fetch_github_releases([handle], cache_root=cache_root, cache_ttl_sec=3600)
    assert len(posts) == 1
    assert posts[0]["title"] == "cached"

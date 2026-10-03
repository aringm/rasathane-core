"""Phase 33-i → 35-xxiv: brief sources.json + load_brief integration.

Phase 35-xxiv: inline `append_sources_to_brief` appendix kaldırıldı (UI
dropdown ile çelişiyordu). Bu dosya artık sadece sources.json ve
load_brief davranışını kapsar; append fonksiyonu silindi.
"""

from datetime import UTC, datetime


class _FakeSource:
    def __init__(self, name: str, category: str):
        self.name = name
        self.category = category


class _FakeArticle:
    def __init__(
        self,
        title: str,
        url: str,
        source_name: str,
        category: str,
        published_at: datetime | None = None,
        fetched_at: datetime | None = None,
    ):
        self.title = title
        self.url = url
        self.source = _FakeSource(source_name, category)
        self.published_at = published_at
        self.fetched_at = fetched_at or datetime.now(UTC)


def test_generate_brief_writes_sources_json_without_inline_appendix(
    tmp_path, monkeypatch
):
    """generate_brief 00-brief.md'ye inline "Kullanılan Kaynaklar" EKLEMEZ,
    ama sources.json hâlâ yazılır (dropdown veri kaynağı).

    Phase 35-xxiv regression: appendix UI dropdown ile çelişiyordu.
    """
    import asyncio

    from rasathane_mcp.core import brief as brief_module

    archive = tmp_path / "archive"

    async def fake_synthesize(prompt):
        return "### Türk Hukuku\n\n[Yargıtay X](https://example.com) gelişme."

    async def fake_gather(session):
        articles = [
            _FakeArticle("Yargıtay X", "https://example.com", "Hürriyet", "tr_hukuk"),
        ]
        return ("## tr_hukuk\n- Yargıtay X (Hürriyet) — özet\n  https://example.com", articles)

    monkeypatch.setattr(brief_module, "synthesize_with_claude", fake_synthesize)
    monkeypatch.setattr(brief_module, "_gather_articles_grouped", fake_gather)

    class FakeSession:
        async def execute(self, *_a, **_k):
            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return []

                    return _S()

            return _R()

    result = asyncio.run(
        brief_module.generate_brief(FakeSession(), archive_root=archive, force=False)
    )
    assert "error" not in result

    today = brief_module._today_iso()
    brief_path = archive / today / "00-brief.md"
    sources_path = archive / today / "sources.json"
    assert brief_path.is_file()
    assert sources_path.is_file()

    md = brief_path.read_text(encoding="utf-8")
    # Phase 35-xxiv: inline appendix YOK
    assert "Kullanılan Kaynaklar" not in md
    assert "### 📎" not in md
    # Markdown muhakeme inject de yok
    assert "muhakeme.ai/emsal" not in md
    # Claude'un içerik linki KORUNUR
    assert "https://example.com" in md

    import json

    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    assert isinstance(sources, list)
    assert len(sources) == 1
    assert sources[0]["title"] == "Yargıtay X"


def test_load_brief_includes_sources(tmp_path):
    """Phase 33-i: load_brief response'una sources.json içeriği eklenir
    (dropdown UI'nın veri kaynağı)."""
    import json

    from rasathane_mcp.core.brief import load_brief

    archive = tmp_path / "archive"
    day_dir = archive / "2026-05-19"
    day_dir.mkdir(parents=True)
    (day_dir / "00-brief.md").write_text("# Brief")
    (day_dir / "sources.json").write_text(
        json.dumps(
            [
                {
                    "title": "X",
                    "url": "https://x",
                    "source_name": "S",
                    "category": "tr_hukuk",
                    "published_at": None,
                    "fetched_at": "2026-05-19T10:00:00+00:00",
                }
            ],
            ensure_ascii=False,
        )
    )

    result = load_brief(archive_root=archive, date="2026-05-19")
    assert "sources" in result
    assert len(result["sources"]) == 1
    assert result["sources"][0]["title"] == "X"


def test_load_brief_no_sources_file(tmp_path):
    """sources.json yoksa sources: []."""
    from rasathane_mcp.core.brief import load_brief

    archive = tmp_path / "archive"
    day_dir = archive / "2026-05-19"
    day_dir.mkdir(parents=True)
    (day_dir / "00-brief.md").write_text("# Brief")

    result = load_brief(archive_root=archive, date="2026-05-19")
    assert result["sources"] == []

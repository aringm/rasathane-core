"""Phase 32-ii: Backwards compatibility testleri.

Eski sürümlerde üretilmiş artefactlar (legacy .txt audio scripts,
result.md format vb.) yeni kod tarafından bozulmadan görüntülenebilmeli.
"""

from __future__ import annotations

from pathlib import Path

# ── deep_analyze: legacy result.md hâlâ "done" sayılır ────────────────


def test_lookup_status_recognizes_legacy_result_md(tmp_path: Path) -> None:
    """Phase 14 legacy single-shot result.md hala 'done' kabul edilir."""
    from rasathane_mcp.core import deep_analyze as core_deep

    job_id = "abcdef1234567890"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "result.md").write_text("# Legacy result", encoding="utf-8")

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "done"
    # Legacy artifact also exposed
    assert "legacy_result" in status.get("artifacts", {})


def test_lookup_status_prefers_summary_over_legacy(tmp_path: Path) -> None:
    """Eğer hem summary.md hem result.md varsa summary.md primary."""
    from rasathane_mcp.core import deep_analyze as core_deep

    job_id = "fedcba0987654321"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    (target / "summary.md").write_text("# New summary", encoding="utf-8")
    (target / "result.md").write_text("# Legacy", encoding="utf-8")

    status = core_deep.lookup_status(archive_root=tmp_path, job_id=job_id)
    assert status["status"] == "done"
    # Her ikisi de artifacts'ta görünür
    artifacts = status.get("artifacts", {})
    assert "summary" in artifacts
    assert "legacy_result" in artifacts


# ── Brief audio: eski tek-spiker mp3 dosyaları korunur ────────────────


def test_load_brief_with_audio_url_works(tmp_path: Path) -> None:
    """Eski .mp3 (tek-spiker veya yeni podcast) farketmez — load_brief audio_url döner."""
    from rasathane_mcp.core.brief import load_brief

    date = "2026-05-10"
    target = tmp_path / date
    target.mkdir()
    (target / "00-brief.md").write_text("# Test", encoding="utf-8")
    (target / "00-brief.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 100)

    payload = load_brief(archive_root=tmp_path, date=date)
    assert payload.get("audio_url") == f"/archive/{date}/00-brief.mp3"


def test_load_brief_without_audio_returns_none_url(tmp_path: Path) -> None:
    from rasathane_mcp.core.brief import load_brief

    date = "2026-05-10"
    target = tmp_path / date
    target.mkdir()
    (target / "00-brief.md").write_text("# Test", encoding="utf-8")

    payload = load_brief(archive_root=tmp_path, date=date)
    assert payload.get("audio_url") is None


# ── Article serialize: title_tr opsiyonel, eski article'lar bozulmaz ──


def test_serialize_article_works_without_title_tr() -> None:
    """metadata.title_tr olmayan eski article'lar normal serialize."""
    from datetime import UTC, datetime

    from conftest import make_fake_article
    from rasathane_mcp.core.serializers import serialize_article

    article = make_fake_article(
        title="Old English article without TR",
        url="https://example.com/old",
    )
    article.id = "uuid-1"
    # title_tr yok — eski article
    article.metadata_ = {"feed_url": "https://example.com/feed"}
    article.fetched_at = datetime(2026, 5, 10, tzinfo=UTC)
    article.published_at = None

    payload = serialize_article(article)
    assert payload["title"] == "Old English article without TR"
    # metadata içinde title_tr yok
    assert "title_tr" not in payload.get("metadata", {})


def test_serialize_article_includes_title_tr_when_present() -> None:
    """metadata.title_tr varsa serialize'da görünür → UI displayTitle bunu kullanır."""
    from datetime import UTC, datetime

    from conftest import make_fake_article
    from rasathane_mcp.core.serializers import serialize_article

    article = make_fake_article(title="New English title")
    article.id = "uuid-2"
    article.metadata_ = {
        "feed_url": "https://example.com/feed",
        "title_tr": "Yeni İngilizce başlık",
    }
    article.fetched_at = datetime(2026, 5, 17, tzinfo=UTC)
    article.published_at = None

    payload = serialize_article(article)
    assert payload["metadata"]["title_tr"] == "Yeni İngilizce başlık"

"""Tests for the dashboard JSON endpoints (Phase 11-ii.3).

Endpoints share core/ business logic with the MCP tools, so we mock at
the same layer (``core_*.session_factory``) here as in test_mcp_server.
The dashboard's per-route helpers (toggle, sync, analyze) are exercised
via httpx + ASGITransport so the FastAPI plumbing (validation, status
codes, BackgroundTasks) is in scope.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from conftest import (
    FakeResult,
    FakeSessionFactory,
    make_fake_article,
    make_fake_source,
)
from httpx import ASGITransport, AsyncClient
from rasathane_mcp.core import articles as core_articles
from rasathane_mcp.core import sources as core_sources
from rasathane_mcp.core import stats as core_stats
from rasathane_mcp.dashboard import app as dashboard_app
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def app() -> Any:
    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── /api/health ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_returns_ok(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rasathane-dashboard"}


# ── Phase 26: /api/system/whisper ─────────────────────────────────────


@pytest.mark.asyncio
async def test_whisper_status_returns_disabled_when_no_env(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHISPER_API_URL set değilse enabled=False."""
    monkeypatch.delenv("WHISPER_API_URL", raising=False)
    async with client:
        response = await client.get("/api/system/whisper")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "api_url": None}


@pytest.mark.asyncio
async def test_whisper_status_returns_enabled_with_api_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHISPER_API_URL set'liyse enabled=True + url payload'da."""
    monkeypatch.setenv("WHISPER_API_URL", "http://localhost:9000")
    async with client:
        response = await client.get("/api/system/whisper")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["api_url"] == "http://localhost:9000"


@pytest.mark.asyncio
async def test_whisper_status_treats_whitespace_as_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHISPER_API_URL boşluk/whitespace olarak set'liyse disabled sayılır."""
    monkeypatch.setenv("WHISPER_API_URL", "   ")
    async with client:
        response = await client.get("/api/system/whisper")
    assert response.status_code == 200
    assert response.json() == {"enabled": False, "api_url": None}


# ── /api/articles ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_articles_returns_paginated_envelope(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    art = make_fake_article(title="One")
    monkeypatch.setattr(
        core_articles, "session_factory", FakeSessionFactory([FakeResult(scalars=[art])])
    )
    async with client:
        response = await client.get("/api/articles?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["offset"] == 0
    assert body["limit"] == 10
    assert body["has_more"] is False  # 1 article < limit 10
    assert body["articles"][0]["title"] == "One"


@pytest.mark.asyncio
async def test_articles_has_more_when_full_page(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    arts = [make_fake_article(title=f"Art {i}") for i in range(3)]
    monkeypatch.setattr(
        core_articles, "session_factory", FakeSessionFactory([FakeResult(scalars=arts)])
    )
    async with client:
        response = await client.get("/api/articles?limit=3")
    assert response.json()["has_more"] is True


@pytest.mark.asyncio
async def test_articles_includes_summary_tr_short(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/api/articles items must include summary_tr_short field with the value."""
    art = make_fake_article(title="Test", summary="EN summary")
    art.summary_tr_short = "Türkçe kısa özet."
    art.summary_tr_long = None
    monkeypatch.setattr(
        core_articles, "session_factory", FakeSessionFactory([FakeResult(scalars=[art])])
    )
    async with client:
        response = await client.get("/api/articles?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["articles"][0]["summary_tr_short"] == "Türkçe kısa özet."
    assert body["articles"][0]["summary_tr_long"] is None


@pytest.mark.asyncio
async def test_articles_summary_tr_short_can_be_null(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default fake article (no Turkish summary) returns null for tr fields."""
    art = make_fake_article(title="T", summary="EN")
    monkeypatch.setattr(
        core_articles, "session_factory", FakeSessionFactory([FakeResult(scalars=[art])])
    )
    async with client:
        response = await client.get("/api/articles?limit=10")
    body = response.json()
    assert body["articles"][0]["summary_tr_short"] is None
    assert body["articles"][0]["summary_tr_long"] is None


# ── /api/sources ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sources_serializes_with_override_fields(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = make_fake_source(name="Muted", enabled=True, is_user_disabled=True)
    monkeypatch.setattr(
        core_sources, "session_factory", FakeSessionFactory([FakeResult(scalars=[src])])
    )
    async with client:
        response = await client.get("/api/sources?enabled_only=false")
    body = response.json()
    assert body[0]["effective_enabled"] is False
    assert body[0]["is_user_disabled"] is True


# ── /api/stats ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats_returns_aggregated_payload(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = make_fake_source(name="A", enabled=True)
    monkeypatch.setattr(
        core_stats,
        "session_factory",
        FakeSessionFactory(
            [
                FakeResult(scalars=[src]),
                FakeResult(scalar_value=10),
                FakeResult(scalar_value=5),
                FakeResult(rows=[]),
            ]
        ),
    )
    async with client:
        response = await client.get("/api/stats")
    body = response.json()
    assert body["sources"]["total"] == 1
    assert body["articles"]["embedded"] == 5


@pytest.mark.asyncio
async def test_stats_separates_user_silenced_from_yaml_disabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 15-i: 2 ayrı kapalı sayım — UI doğru etiketleyebilsin.

    Senaryo: 4 source — 1 efektif aktif, 1 kullanıcı sustırması,
    1 yaml-kapalı, 1 her ikisi (overlap).
    """
    sources = [
        make_fake_source(name="Active", enabled=True, is_user_disabled=False),
        make_fake_source(name="UserSilenced", enabled=True, is_user_disabled=True),
        make_fake_source(name="YamlOff", enabled=False, is_user_disabled=False),
        make_fake_source(name="BothOff", enabled=False, is_user_disabled=True),
    ]
    monkeypatch.setattr(
        core_stats,
        "session_factory",
        FakeSessionFactory(
            [
                FakeResult(scalars=sources),
                FakeResult(scalar_value=0),
                FakeResult(scalar_value=0),
                FakeResult(rows=[]),
            ]
        ),
    )
    async with client:
        response = await client.get("/api/stats")
    body = response.json()
    assert body["sources"]["total"] == 4
    assert body["sources"]["enabled"] == 1  # only "Active"
    assert body["sources"]["disabled"] == 3  # total - enabled
    # Yeni: ayrık sayımlar (Venn — overlap her iki sayımda da gözükür)
    assert body["sources"]["user_silenced"] == 2  # UserSilenced + BothOff
    assert body["sources"]["yaml_disabled"] == 2  # YamlOff + BothOff


# ── /api/sources/{id}/toggle ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_toggle_returns_effective_state(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_id = uuid.uuid4()
    captured: dict[str, Any] = {}

    async def fake_set_user_disabled(
        _session: Any, source_id: uuid.UUID, *, disabled: bool
    ) -> bool:
        captured["source_id"] = source_id
        captured["disabled"] = disabled
        return not disabled  # effective = !disabled when feeds.yaml enabled=True

    # Replace the helper in app.py's namespace (imported by name).
    monkeypatch.setattr(dashboard_app, "set_user_disabled", fake_set_user_disabled)
    monkeypatch.setattr(dashboard_app, "session_factory", FakeSessionFactory([]))

    async with client:
        response = await client.post(f"/api/sources/{src_id}/toggle", json={"disabled": True})
    assert response.status_code == 200
    body = response.json()
    assert body["effective_enabled"] is False
    assert body["is_user_disabled"] is True
    assert captured["source_id"] == src_id


@pytest.mark.asyncio
async def test_toggle_unknown_source_returns_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def raises(*_args: Any, **_kw: Any) -> bool:
        raise LookupError("source x not found")

    monkeypatch.setattr(dashboard_app, "set_user_disabled", raises)
    monkeypatch.setattr(dashboard_app, "session_factory", FakeSessionFactory([]))

    async with client:
        response = await client.post(f"/api/sources/{uuid.uuid4()}/toggle", json={"disabled": True})
    assert response.status_code == 404


# ── /api/sources/{id}/sync ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_unknown_source_returns_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dashboard_app,
        "session_factory",
        FakeSessionFactory([FakeResult(scalar_value=None)]),
    )
    async with client:
        response = await client.post(f"/api/sources/{uuid.uuid4()}/sync")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_sync_known_source_queues_background_task(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_id = uuid.uuid4()
    monkeypatch.setattr(
        dashboard_app,
        "session_factory",
        FakeSessionFactory([FakeResult(scalar_value=src_id)]),
    )
    # Stub out the actual fetcher so the background task is a no-op.
    invoked = asyncio.Event()

    async def fake_bg(_source_id: uuid.UUID) -> None:
        invoked.set()

    monkeypatch.setattr(dashboard_app, "_sync_source_in_background", fake_bg)

    async with client:
        response = await client.post(f"/api/sources/{src_id}/sync")
    assert response.status_code == 200
    assert response.json() == {"status": "queued", "id": str(src_id)}
    # BackgroundTasks runs after response — wait briefly for it.
    await asyncio.wait_for(invoked.wait(), timeout=2.0)


# ── Phase 20-i: tüm akışı yenile (sync-all) ──────────────────────────


@pytest.mark.asyncio
async def test_sync_all_returns_202_and_queues_background(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/sources/sync-all → 202 + scope=all_enabled, background task spawn."""
    invoked = asyncio.Event()

    async def fake_bg() -> None:
        invoked.set()

    monkeypatch.setattr(dashboard_app, "_sync_all_in_background", fake_bg)

    async with client:
        response = await client.post("/api/sources/sync-all")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["scope"] == "all_enabled"
    # Background task triggered after response
    await asyncio.wait_for(invoked.wait(), timeout=2.0)


# ── /api/analyze ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/page",
        "https://random.site/article",
    ],
)
@pytest.mark.asyncio
async def test_analyze_unknown_url_returns_error(client: AsyncClient, url: str) -> None:
    async with client:
        response = await client.post("/api/analyze", json={"url": url})
    assert response.status_code == 200
    body = response.json()
    assert body["detected_type"] == "unknown"
    assert "error" in body


@pytest.mark.asyncio
async def test_analyze_youtube_returns_metadata(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """YouTube URL → ingestion.youtube.fetch_metadata sonucunu sarar."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _FakeMeta:
        video_id: str = "abc123"
        title: str = "Test video"
        channel: str = "Test Channel"
        duration_seconds: int = 600
        url: str = "https://www.youtube.com/watch?v=abc123"

    async def fake_fetch(url: str):  # type: ignore[no-untyped-def]
        return _FakeMeta()

    monkeypatch.setattr("ingestion.youtube.fetch_metadata", fake_fetch)

    async with client:
        response = await client.post(
            "/api/analyze", json={"url": "https://www.youtube.com/watch?v=abc123"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["detected_type"] == "youtube"
    assert body["metadata"]["video_id"] == "abc123"
    assert body["metadata"]["title"] == "Test video"
    assert body["metadata"]["duration_seconds"] == 600


@pytest.mark.asyncio
async def test_analyze_github_returns_metadata(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _FakeRepo:
        owner: str = "anthropic"
        name: str = "anthropic-cookbook"
        full_name: str = "anthropic/anthropic-cookbook"
        description: str | None = "Recipes for Claude"
        primary_language: str | None = "Python"
        stars: int = 12345
        forks: int = 678
        default_branch: str = "main"
        url: str = "https://github.com/anthropic/anthropic-cookbook"

    async def fake_fetch(url: str):  # type: ignore[no-untyped-def]
        return _FakeRepo()

    monkeypatch.setattr("ingestion.github.fetch_repo_metadata", fake_fetch)

    async with client:
        response = await client.post(
            "/api/analyze", json={"url": "https://github.com/anthropic/anthropic-cookbook"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["detected_type"] == "github"
    assert body["metadata"]["full_name"] == "anthropic/anthropic-cookbook"
    assert body["metadata"]["stars"] == 12345


@pytest.mark.asyncio
async def test_analyze_rejects_empty_url(client: AsyncClient) -> None:
    async with client:
        response = await client.post("/api/analyze", json={"url": ""})
    assert response.status_code == 422  # pydantic min_length=1


# ── HTML pages ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_index_renders_with_alpine(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/")
    assert response.status_code == 200
    body = response.text
    # Page-specific marker (from index.html template).
    # Phase 34-ii: liveStream section /canli-akis sayfasına taşındı; index
    # şimdi sadece brief panel + past briefs içeriyor.
    assert "briefPanel()" in body
    assert "pastBriefs()" in body
    # Base layout marker — proves _base.html was extended.
    assert "Rasathane" in body
    # Alpine vendored, not CDN.
    assert "/static/alpine.min.js" in body
    # Logo link to muhakeme brand asset.
    assert "/static/logo.png" in body


@pytest.mark.asyncio
async def test_static_logo_served(client: AsyncClient) -> None:
    """Vendored logo reachable at /static/ — survives offline use."""
    async with client:
        response = await client.get("/static/logo.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    # Sanity: PNG magic bytes.
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


# ── Phase 11-ii.7: Turkish consistency + professional layout ──────────


@pytest.mark.asyncio
async def test_home_uses_turkish_brief_label(client: AsyncClient) -> None:
    """'Brief' → 'Gündem' rename is user-facing only (API path unchanged).

    Phase 22-ii: KPI bar kaldırıldı (geliştirici metriği — ratio
    sayıları kullanıcı için anlamsız). Akışı Yenile butonu compact
    form'da brief panel block-header'a taşındı.
    Phase 30: page-header (eyebrow + h1) ve section h2 başlıkları
    kaldırıldı; yerine tek modern TR tarih başlığı (formatDateTR).
    Phase 31: tarih ortalanmış hero başlığa, tıklanınca aylık takvim
    (Pzt-Paz, milli + dini bayramlar işaretli). Aksiyon butonları
    modern pill grubu (Bugüne dön / Gündem üret / Sesli oku /
    Akışı yenile / Kaydet).
    """
    async with client:
        response = await client.get("/")
    body = response.text
    # Phase 30: artık raw DOM'da "Bugünün Gündemi" yok — TR tarih
    # client-rendered, Alpine x-text formatDateTR(data.date)
    assert "Bugünün Gündemi" not in body
    # Phase 31: yeni hero başlık + aylık takvim
    assert "brief-hero-date" in body  # tıklanabilir hero başlık
    assert "brief-calendar" in body  # aylık takvim popover
    assert "monthGrid()" in body  # takvim grid generator
    assert "TR_NATIONAL_HOLIDAYS" in body  # milli tatil verisi
    assert "TR_RELIGIOUS_HOLIDAYS" in body  # dini bayram verisi
    assert "formatDateTR" in body  # JS formatter mevcut
    assert "TR_MONTHS" in body  # ay isim listesi
    # Phase 34-ii: "Canlı Akış" hâlâ nav link metni olarak görünür.
    assert "Canlı Akış" in body
    # Phase 32-v.3: Nav 'Gündem' → 'Bülten' rename
    assert ">Bülten</a>" in body
    # Phase 33-i: brief sources accordion'unda Türk Hukuku kategori
    # label'ı briefSources() içinde tanımlı.
    assert 'label: "Türk Hukuku"' in body
    # Phase 22-ii: KPI bar kaldırıldı — bu metinler artık olmamalı
    assert "kpiBar()" not in body
    assert "Aktif Kaynak" not in body
    assert "Embed Kapsamı" not in body
    # Phase 22-ii: Akışı Yenile butonu hâlâ erişilebilir (taşındı)
    assert "syncAllButton()" in body
    assert "Akışı yenile" in body
    # Phase 31: aksiyon pill butonları + sesli oku label'ı
    assert "btn-pill" in body
    assert "Sesli oku" in body
    assert "Bugüne dön" in body
    # Phase 30: önceki gündemler listesi + custom audio player
    assert "past-briefs" in body
    assert "Önceki gündemler" in body
    assert "audioPlayer(" in body
    assert "pastBriefs()" in body


@pytest.mark.asyncio
async def test_pages_use_consistent_nav_and_footer(client: AsyncClient) -> None:
    """Every page shares the new top nav + footer + 'Analiz' (not 'Analyze').

    Phase 16-ii: footer "Phase X" geliştirici etiketinden ürün adına
    ("Rasathane") indirildi — kullanıcı yüzeyinde versiyon görünmesin.
    """
    async with client:
        for path in ("/", "/sources", "/analyze"):
            response = await client.get(path)
            assert response.status_code == 200
            body = response.text
            # Phase 34-ii: nav reorder — Canlı Akış sayfa eklendi,
            # Sosyal Medya nav silindi (içerik /sources#sosyal'a taşındı),
            # Planlar → Yapılacaklar rename.
            assert ">Bülten</a>" in body
            assert ">Canlı Akış</a>" in body
            assert ">Analiz</a>" in body
            assert ">Kütüphane</a>" in body
            assert ">Yapılacaklar</a>" in body
            assert ">Kaynaklar</a>" in body
            assert ">Stüdyo</a>" in body
            # Phase 34-ii: Sosyal Medya nav silindi.
            assert ">Sosyal Medya</a>" not in body
            # Footer with product name + repo link.
            assert "github.com/aringm/rasathane" in body
            # No dev-language Phase tags leak into UI footer
            assert "Phase 11-ii" not in body


@pytest.mark.asyncio
async def test_sources_page_renders(client: AsyncClient) -> None:
    async with client:
        response = await client.get("/sources")
    assert response.status_code == 200
    body = response.text
    assert "sourcesPage()" in body  # template Alpine factory
    assert "Kaynaklar" in body


@pytest.mark.asyncio
async def test_analyze_page_renders(client: AsyncClient) -> None:
    """Phase 16-ii: eyebrow 'URL Analizi' → 'Bağlantı Analizi' (Türkçe ürün dili)."""
    async with client:
        response = await client.get("/analyze")
    assert response.status_code == 200
    body = response.text
    assert "analyzePage()" in body
    assert "Bağlantı Analizi" in body


@pytest.mark.asyncio
async def test_static_alpine_served(client: AsyncClient) -> None:
    """Vendored Alpine must be reachable at /static/ — offline guarantee."""
    async with client:
        response = await client.get("/static/alpine.min.js")
    assert response.status_code == 200
    # Sanity: the file is the real Alpine script, not a 404 page.
    assert "Alpine" in response.text

"""Phase 32-v.3: Comprehensive tests for nav rename, 2-tab sources,
mindmap modal, agent profiles, auto-tagging, unanalyzed YouTube videos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from llm.tts import (
    _agent_profile_defaults,
    get_active_agent_profiles,
    load_agent_profiles,
    save_agent_profiles,
)
from rasathane_mcp.core.deep_analyze import (
    _collect_analyzed_urls,
    extract_tags_from_summary,
)
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client + isolated paths."""
    monkeypatch.setenv(
        "RASATHANE_AGENT_PROFILES_PATH",
        str(tmp_path / "agent_profiles.json"),
    )
    monkeypatch.setenv(
        "RASATHANE_VOICE_OVERRIDES_PATH",
        str(tmp_path / "voice_overrides.json"),
    )
    # Phase 35-iii: RASATHANE_TR_PRONUNCIATION_PATH kaldırıldı (lab silindi)
    return TestClient(create_app())


# ── Nav rename + reorder ────────────────────────────────────────────────


def test_nav_uses_new_tr_labels(client: TestClient) -> None:
    """Phase 35-xi: Bülten / Canlı Akış / Analiz / Kütüphane / Yapılacaklar / Kaynaklar / Stüdyo."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    for label in (
        "Bülten",
        "Canlı Akış",
        "Analiz",
        "Kütüphane",
        "Yapılacaklar",
        "Kaynaklar",
        "Stüdyo",
    ):
        assert f">{label}</a>" in body, f"Nav label '{label}' bulunamadı"
    # Phase 34-ii: Sosyal Medya nav silindi (içerik /sources#sosyal'a taşındı)
    assert ">Sosyal Medya</a>" not in body
    # Phase 34-ii: Planlar → Yapılacaklar rename
    assert ">Planlar</a>" not in body


def test_nav_uses_new_order(client: TestClient) -> None:
    """Nav sırası: Bülten → Canlı Akış → Analiz → Kütüphane → Yapılacaklar → Kaynaklar → Stüdyo."""
    r = client.get("/")
    body = r.text
    expected_order = [
        "Bülten",
        "Canlı Akış",
        "Analiz",
        "Kütüphane",
        "Yapılacaklar",
        "Kaynaklar",
        "Stüdyo",
    ]
    positions = [body.find(f">{label}</a>") for label in expected_order]
    assert all(p > 0 for p in positions), "Bazı nav label'ları bulunamadı"
    assert positions == sorted(positions), "Nav sırası beklenen düzende değil"


def test_home_title_is_bulten(client: TestClient) -> None:
    """Phase 32-v.3: index.html title 'Bülten'."""
    r = client.get("/")
    assert "Rasathane · Bülten" in r.text
    assert "Rasathane · Gündem" not in r.text


def test_social_watch_page_uses_sosyal_medya_label(client: TestClient) -> None:
    """Phase 34-ii: /social-watch artık /sources#sosyal'a yönlendiriyor.

    Eski adres 301 redirect döner; UI içeriği /sources sub-tab'ında
    yer alır. Bu test, redirect sonrası /sources sayfasının "Sosyal Medya
    Kaynakları" sub-tab başlığını barındırdığını doğrular.
    """
    r = client.get("/social-watch", follow_redirects=False)
    assert r.status_code == 301
    assert r.headers["location"] == "/sources#sosyal"
    # Sub-tab başlığı /sources içinde
    r2 = client.get("/sources")
    body = r2.text
    assert "Sosyal Medya Kaynakları" in body


def test_voices_page_uses_studio_label(client: TestClient) -> None:
    """Phase 35-xi: /voices sayfası 'Stüdyo' H1 + nav link.

    Phase 35-ii'deki "Live Console · Kayıt Odası" eyebrow + uzun açıklama
    Phase 35-xi'de kullanıcı talebiyle kaldırıldı; sadece yalın "Stüdyo"
    H1 ve "Stüdyo" nav linki kaldı.
    """
    r = client.get("/voices")
    body = r.text
    assert "Stüdyo" in body  # H1 + navbar link
    # Phase 35-xi: eski eyebrow + açıklama bloğu kaldırıldı
    assert "Live Console" not in body
    assert "Kayıt Odası" not in body


# ── Sources 2-tab ───────────────────────────────────────────────────────


def test_sources_page_has_2_tab_switcher(client: TestClient) -> None:
    """Phase 32-v.3 + Phase 34-ii: /sources üst tab bar 2 sub-tab.

    Phase 34-ii'de label rename oldu: 'Bülten Kaynakları' → 'Canlı Akış
    Kaynakları' (terminoloji canli-akis sayfasıyla hizalandı). Sub-tab
    state name'leri ('bulletin'/'social') koruyor.
    """
    r = client.get("/sources")
    assert r.status_code == 200
    body = r.text
    assert "Canlı Akış Kaynakları" in body
    assert "Sosyal Medya Kaynakları" in body
    assert "tab === 'bulletin'" in body
    assert "tab === 'social'" in body
    assert "loadSocialPeople" in body  # JS fn
    # Phase 34-ii: socialWatchPage UI içeriği sub-tab'a taşındı
    assert "socialWatchPage()" in body


# ── Mindmap full-screen modal ──────────────────────────────────────────


def test_analyze_page_has_mindmap_fullscreen_modal(client: TestClient) -> None:
    """Phase 32-v.3: analyze.html mindmap full-screen modal HTML + button."""
    r = client.get("/analyze")
    body = r.text
    assert "mindmapFullscreen" in body  # Alpine state
    assert "btn-fullscreen-mindmap" in body  # Tam ekran butonu class
    assert "mindmap-modal-overlay" in body  # Modal container
    assert "@keydown.escape.window" in body  # ESC close
    assert "@click.self" in body  # outside-click close


# ── Unanalyzed YouTube videos endpoint ─────────────────────────────────


def test_youtube_unanalyzed_endpoint_shape(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 32-v.3: /api/youtube/unanalyzed 200 + videos/count shape.

    Endpoint DB session_factory kullanır; testte fake mock ile videos=[] döner.
    """
    from rasathane_mcp.core import deep_analyze as core_deep

    async def fake_list(session, **_kwargs):
        return [
            {
                "url": "https://yt/x",
                "title": "Test",
                "channel_name": "Kanal",
                "published_at": None,
                "fetched_at": None,
            },
        ]

    monkeypatch.setattr(core_deep, "list_unanalyzed_youtube_videos", fake_list)
    # Endpoint içindeki async with session_factory()'yi de mock'la
    from unittest.mock import AsyncMock, MagicMock

    fake_session_ctx = MagicMock()
    fake_session_ctx.__aenter__ = AsyncMock(return_value=MagicMock())
    fake_session_ctx.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        lambda: fake_session_ctx,
    )

    r = client.get("/api/youtube/unanalyzed?limit=5&days=14")
    assert r.status_code == 200
    body = r.json()
    assert "videos" in body
    assert "count" in body
    assert body["count"] == 1
    assert body["videos"][0]["url"] == "https://yt/x"


def test_collect_analyzed_urls_filters_correctly(tmp_path: Path) -> None:
    """`_collect_analyzed_urls` deep/ altındaki meta.json'lardan URL set döner."""
    deep_root = tmp_path / "deep"
    deep_root.mkdir()
    # job 1: valid url
    (deep_root / "job1").mkdir()
    (deep_root / "job1" / "meta.json").write_text(
        json.dumps({"url": "https://youtube.com/watch?v=abc", "type": "youtube"}),
        encoding="utf-8",
    )
    # job 2: no url field
    (deep_root / "job2").mkdir()
    (deep_root / "job2" / "meta.json").write_text(json.dumps({"type": "youtube"}), encoding="utf-8")
    # job 3: corrupt
    (deep_root / "job3").mkdir()
    (deep_root / "job3" / "meta.json").write_text("not valid json", encoding="utf-8")
    # dot-prefixed (atlanmalı)
    (deep_root / ".tmp").mkdir()

    urls = _collect_analyzed_urls(tmp_path)
    assert urls == {"https://youtube.com/watch?v=abc"}


# ── Auto-tagging (extract_tags_from_summary) ───────────────────────────


def test_extract_tags_returns_empty_when_no_comment() -> None:
    assert extract_tags_from_summary("just markdown") == []
    assert extract_tags_from_summary("") == []


def test_extract_tags_parses_html_comment_format() -> None:
    md = """### Konunun özü
foo bar.

<!-- TAGS: Karpathy, AI, transformer, eğitim-içeriği -->
"""
    tags = extract_tags_from_summary(md)
    assert tags == ["karpathy", "ai", "transformer", "eğitim-içeriği"]


def test_extract_tags_filters_too_short_and_too_long() -> None:
    md = "<!-- TAGS: a, valid-tag, " + "x" * 50 + " -->"
    tags = extract_tags_from_summary(md)
    # "a" çok kısa, "x"*50 çok uzun → atlandı, sadece "valid-tag" kaldı
    assert tags == ["valid-tag"]


def test_extract_tags_dedupes_lowercase() -> None:
    md = "<!-- TAGS: AI, ai, Anthropic, ANTHROPIC -->"
    tags = extract_tags_from_summary(md)
    assert tags == ["ai", "anthropic"]


def test_extract_tags_strips_quotes() -> None:
    """Quote'lu tag'leri (örnek prompt'taki gibi) düzgün parse eder.

    Not: <bracket> kullanma — HTML comment delimiter ile çakışır.
    """
    md = "<!-- TAGS: \"AI\", 'transformer', deepseek -->"
    tags = extract_tags_from_summary(md)
    assert "ai" in tags
    assert "transformer" in tags
    assert "deepseek" in tags


# ── Agent Profiles backend ─────────────────────────────────────────────


def test_agent_profile_defaults_has_pool_and_modes() -> None:
    """Phase 32-v.4: Default {agents, modes} schema."""
    defaults = _agent_profile_defaults()
    assert set(defaults.keys()) == {"agents", "modes"}
    assert isinstance(defaults["agents"], dict)
    assert set(defaults["modes"].keys()) == {"brief", "youtube"}
    assert len(defaults["modes"]["brief"]) == 3
    assert len(defaults["modes"]["youtube"]) == 3


def test_agent_profile_defaults_central_pool_includes_mehmet() -> None:
    """Phase 32-v.4 / Phase 33-i: Mehmet havuzda + voice_id Adam TR."""
    defaults = _agent_profile_defaults()
    assert "mehmet" in defaults["agents"]
    assert defaults["agents"]["mehmet"]["name"] == "Mehmet"
    # Phase 33-i: Burak Namlı → Adam TR (yumuşak ton)
    assert defaults["agents"]["mehmet"]["voice_id"] == "RXCCWbOxP7Hisa63Xsv5"


def test_agent_profile_defaults_cross_mode_consistency() -> None:
    """Filiz hem brief hem youtube'da → aynı agent_id (aynı ses)."""
    defaults = _agent_profile_defaults()
    brief_agent_ids = {s["agent_id"] for s in defaults["modes"]["brief"]}
    youtube_agent_ids = {s["agent_id"] for s in defaults["modes"]["youtube"]}
    # Filiz her ikisinde de
    assert "filiz" in brief_agent_ids
    assert "filiz" in youtube_agent_ids


def test_agent_profiles_load_save_round_trip_new_schema(client: TestClient, tmp_path: Path) -> None:
    """Phase 32-v.4: save + load = same data (yeni schema)."""
    data = {
        "agents": {
            "custom": {"name": "Custom Filiz", "voice_id": "VID1"},
        },
        "modes": {
            "brief": [{"agent_id": "custom", "role": "Test rol"}],
            "youtube": [],
        },
    }
    assert save_agent_profiles(data) is True
    loaded = load_agent_profiles()
    assert loaded == data


def test_get_active_agent_profiles_user_overrides_pool(client: TestClient, tmp_path: Path) -> None:
    """User havuz tamamen ezerse defaults atlanır."""
    save_agent_profiles(
        {
            "agents": {"alper": {"name": "Alper", "voice_id": "AVID"}},
            "modes": {"brief": [{"agent_id": "alper", "role": "Spiker"}], "youtube": []},
        }
    )
    active = get_active_agent_profiles("brief")
    assert len(active) == 1
    assert active[0]["name"] == "Alper"
    assert active[0]["voice_id"] == "AVID"


def test_get_active_agent_profiles_missing_agent_skipped(
    client: TestClient, tmp_path: Path
) -> None:
    """Mode'da agent_id var ama havuzda yok → slot atlanır + warn log."""
    save_agent_profiles(
        {
            "agents": {"a": {"name": "A", "voice_id": "VID"}},
            "modes": {
                "brief": [
                    {"agent_id": "a", "role": "Rol A"},
                    {"agent_id": "missing", "role": "Rol M"},
                ],
                "youtube": [],
            },
        }
    )
    active = get_active_agent_profiles("brief")
    # "missing" agent havuzda yok → atlandı
    assert len(active) == 1
    assert active[0]["agent_id"] == "a"


def test_agent_profiles_get_endpoint_new_schema(client: TestClient) -> None:
    """Phase 32-v.4: GET endpoint {defaults, current, active} shape."""
    r = client.get("/api/tts/agent-profiles")
    assert r.status_code == 200
    body = r.json()
    assert "defaults" in body
    assert "current" in body
    assert "active" in body
    # Defaults yeni schema
    assert set(body["defaults"].keys()) == {"agents", "modes"}
    assert set(body["current"].keys()) == {"agents", "modes"}
    # Active resolved listesi
    assert set(body["active"].keys()) == {"brief", "youtube"}
    assert len(body["active"]["brief"]) == 3
    assert len(body["active"]["youtube"]) == 3


def test_agent_profiles_post_saves_new_schema(client: TestClient) -> None:
    """Phase 32-v.4: POST yeni schema body + GET reflects."""
    payload = {
        "agents": {
            "sezen": {"name": "Sezen", "voice_id": "TEST_VID"},
        },
        "modes": {
            "brief": [{"agent_id": "sezen", "role": "Spiker"}],
            "youtube": [],
        },
    }
    r = client.post("/api/tts/agent-profiles", json=payload)
    assert r.status_code == 200, r.text
    # GET reflects
    rg = client.get("/api/tts/agent-profiles")
    body = rg.json()
    assert body["current"] == payload
    assert body["active"]["brief"][0]["name"] == "Sezen"


def test_agent_profiles_post_rejects_invalid_agent_id_in_mode(
    client: TestClient,
) -> None:
    """Mode slot agent_id havuzda yoksa 422."""
    r = client.post(
        "/api/tts/agent-profiles",
        json={
            "agents": {"a": {"name": "A", "voice_id": "V"}},
            "modes": {"brief": [{"agent_id": "missing", "role": "X"}], "youtube": []},
        },
    )
    assert r.status_code == 422


def test_agent_profiles_post_rejects_long_name(client: TestClient) -> None:
    """Agent name > 80 char reject."""
    r = client.post(
        "/api/tts/agent-profiles",
        json={
            "agents": {"a": {"name": "x" * 100, "voice_id": "V"}},
            "modes": {"brief": [], "youtube": []},
        },
    )
    assert r.status_code == 422


def test_legacy_schema_auto_migrated(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 32-v.4: eski schema dosyası varsa load'ta otomatik migrate."""
    path = tmp_path / "agent_profiles.json"
    # Eski format (Phase 32-v.3)
    legacy = {
        "brief": [
            {"slot": 0, "name": "Filiz", "role": "Spiker", "voice_id": "VID_F"},
            {"slot": 1, "name": "Mehmet", "role": "Hukuk", "voice_id": "VID_M"},
        ],
        "youtube": [
            {"slot": 0, "name": "Filiz", "role": "Spiker", "voice_id": "VID_F"},
        ],
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setenv("RASATHANE_AGENT_PROFILES_PATH", str(path))

    loaded = load_agent_profiles()
    assert "agents" in loaded
    assert "modes" in loaded
    # Filiz tek agent_id'ye eşlenmeli (cross-mode tutarlılık)
    assert "filiz" in loaded["agents"]
    assert loaded["agents"]["filiz"]["voice_id"] == "VID_F"

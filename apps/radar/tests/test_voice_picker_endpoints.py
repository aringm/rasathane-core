"""Phase 32-v: Voice picker API endpoint testleri.

`/api/tts/voices` (ElevenLabs API mock), `/api/tts/preview`,
`/api/tts/voice-config` GET + POST.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Test client + izole voice_overrides path."""
    monkeypatch.setenv(
        "RASATHANE_VOICE_OVERRIDES_PATH",
        str(tmp_path / "voice_overrides.json"),
    )
    return TestClient(create_app())


# ── /api/tts/voices ─────────────────────────────────────────────────────


def test_voices_returns_503_when_api_key_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ELEVENLABS_API_KEY env yoksa → 503 + açıklayıcı detail."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    r = client.get("/api/tts/voices")
    assert r.status_code == 503
    assert "ELEVENLABS_API_KEY" in r.json()["detail"]


def test_voices_returns_503_when_api_key_whitespace_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitespace-only key → 503 (boş string ile aynı muamele)."""
    monkeypatch.setenv("ELEVENLABS_API_KEY", "   ")
    r = client.get("/api/tts/voices")
    assert r.status_code == 503


# ── /api/tts/preview ────────────────────────────────────────────────────


def test_preview_requires_voice_id(client: TestClient) -> None:
    """voice_id alanı zorunlu → 422."""
    r = client.post("/api/tts/preview", json={})
    assert r.status_code == 422
    assert "voice_id" in r.json()["detail"]


def test_preview_rejects_too_long_voice_id(client: TestClient) -> None:
    """voice_id > 64 char → 422."""
    r = client.post("/api/tts/preview", json={"voice_id": "x" * 100})
    assert r.status_code == 422


def test_preview_returns_503_without_api_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Voice ID valid ama API key yok → 503."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    r = client.post("/api/tts/preview", json={"voice_id": "valid_voice_xyz"})
    assert r.status_code == 503


# ── /api/tts/voice-config GET ───────────────────────────────────────────


def test_voice_config_get_returns_overrides_and_defaults(
    client: TestClient, tmp_path: Path
) -> None:
    """GET → overrides + defaults dict döner."""
    r = client.get("/api/tts/voice-config")
    assert r.status_code == 200
    body = r.json()
    assert "overrides" in body
    assert "defaults" in body
    # Defaults shape
    assert "elevenlabs" in body["defaults"]
    assert set(body["defaults"]["elevenlabs"]["brief"].keys()) == {"Filiz", "Mehmet", "Burak"}
    assert set(body["defaults"]["elevenlabs"]["youtube"].keys()) == {"Filiz", "Burak", "Esra"}


def test_voice_config_get_reflects_saved_overrides(client: TestClient) -> None:
    """POST → GET → kaydedilen override geri okunur."""
    # Önce POST
    payload = {
        "elevenlabs": {
            "brief": {"Filiz": "CUSTOM_FILIZ_ID"},
        }
    }
    rp = client.post("/api/tts/voice-config", json=payload)
    assert rp.status_code == 200
    # Sonra GET
    rg = client.get("/api/tts/voice-config")
    body = rg.json()
    assert body["overrides"] == payload


# ── /api/tts/voice-config POST ──────────────────────────────────────────


def test_voice_config_post_saves_valid_config(client: TestClient) -> None:
    """Geçerli config kaydedilir + status ok döner."""
    payload = {
        "elevenlabs": {
            "brief": {"Filiz": "abc", "Mehmet": "def", "Burak": "ghi"},
            "youtube": {"Filiz": "abc", "Burak": "ghi", "Esra": "jkl"},
        }
    }
    r = client.post("/api/tts/voice-config", json=payload)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["saved"] == payload


def test_voice_config_post_rejects_unknown_provider(client: TestClient) -> None:
    """elevenlabs dışı provider → 422."""
    r = client.post("/api/tts/voice-config", json={"google_tts": {"brief": {}}})
    assert r.status_code == 422
    assert "provider" in r.json()["detail"].lower()


def test_voice_config_post_rejects_unknown_role(client: TestClient) -> None:
    """brief|youtube dışı role → 422."""
    r = client.post(
        "/api/tts/voice-config",
        json={"elevenlabs": {"podcast_pro": {"Filiz": "x"}}},
    )
    assert r.status_code == 422
    assert "role" in r.json()["detail"].lower()


def test_voice_config_post_skips_empty_voice_id(client: TestClient) -> None:
    """voice_id boş ise saved'a girmiyor (kullanıcı seçimi sıfırlama sinyali)."""
    r = client.post(
        "/api/tts/voice-config",
        json={"elevenlabs": {"brief": {"Filiz": "", "Mehmet": "valid_id"}}},
    )
    assert r.status_code == 200
    saved = r.json()["saved"]
    assert "Filiz" not in saved["elevenlabs"]["brief"]
    assert saved["elevenlabs"]["brief"]["Mehmet"] == "valid_id"


def test_voice_config_post_rejects_too_long_voice_id(client: TestClient) -> None:
    """64+ char voice_id → 422."""
    r = client.post(
        "/api/tts/voice-config",
        json={"elevenlabs": {"brief": {"Filiz": "x" * 100}}},
    )
    assert r.status_code == 422


def test_voice_config_post_replace_semantics(client: TestClient) -> None:
    """İkinci POST tüm config'i replace eder (partial merge sorumluluğu client'ta)."""
    client.post("/api/tts/voice-config", json={"elevenlabs": {"brief": {"Filiz": "first"}}})
    client.post(
        "/api/tts/voice-config",
        json={"elevenlabs": {"brief": {"Mehmet": "second"}}},
    )
    body = client.get("/api/tts/voice-config").json()
    assert body["overrides"] == {"elevenlabs": {"brief": {"Mehmet": "second"}}}


# ── /voices page render ─────────────────────────────────────────────────


def test_voices_page_renders_html(client: TestClient) -> None:
    """/voices route 200 + HTML template render eder."""
    r = client.get("/voices")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    # Phase 35-xi: H1 "Stüdyo" (Phase 35-ii rename + Kayıt Odası kaldırıldı); Alpine fn studio()
    assert "Stüdyo" in r.text
    assert "function studio()" in r.text  # Alpine fn referansı


def test_voices_link_in_navbar(client: TestClient) -> None:
    """_base.html navbar'da Sesler linki olmalı."""
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/voices"' in r.text


# ── Phase 35-xi: SELECTABLE_VOICE_IDS whitelist ─────────────────────────


def test_selectable_voice_ids_contains_tr_native_plus_matilda() -> None:
    """Phase 35-xi: whitelist TR-native voice'ları + Matilda içerir.

    Anglofon erkek baritone voice'lar (Brian, Adam, vb. — Phase 35-x öncesi
    DEVNULL hung yapanlar) bilinçli olarak whitelist dışı. Validation
    yapıldığında genişletilebilir.
    """
    from llm.tts import (
        ELEVENLABS_DEFAULT_VOICES,
        ELEVENLABS_TR_NATIVE_VOICES,
        SELECTABLE_VOICE_IDS,
    )

    # Tüm TR-native voice ID'leri whitelist'te
    for name, vid in ELEVENLABS_TR_NATIVE_VOICES.items():
        assert vid in SELECTABLE_VOICE_IDS, f"TR-native {name} whitelist dışı"

    # Matilda (anglofon kadın, Phase 35-x test edildi)
    assert ELEVENLABS_DEFAULT_VOICES["Matilda"] in SELECTABLE_VOICE_IDS

    # Anglofon erkek baritone'lar whitelist dışı
    for excluded in ("Brian", "Adam", "George", "Daniel", "Eric", "Chris", "Liam"):
        if excluded in ELEVENLABS_DEFAULT_VOICES:
            assert (
                ELEVENLABS_DEFAULT_VOICES[excluded] not in SELECTABLE_VOICE_IDS
            ), f"{excluded} whitelist'e sızdı — Phase 35-x DEVNULL fix öncesi hung yapıyordu"


def test_voices_endpoint_filters_to_whitelist(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Phase 35-xi: /api/tts/voices response sadece SELECTABLE_VOICE_IDS'i döner.

    ElevenLabs API mock'lanmış 4 voice döner: 2'si whitelist'te (Adam TR,
    Matilda), 2'si dışında (Brian baritone, Bill). Response sadece 2 voice
    içermeli.
    """
    import respx
    from httpx import Response
    from llm.tts import ELEVENLABS_DEFAULT_VOICES, ELEVENLABS_TR_NATIVE_VOICES

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")
    # Cache'i tmp'ye yönlendir → her test fresh API call yapar
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app._ELEVENLABS_VOICES_CACHE_PATH",
        tmp_path / "voices_cache.json",
    )

    mock_voices = {
        "voices": [
            {"voice_id": ELEVENLABS_TR_NATIVE_VOICES["Adam TR"], "name": "Adam TR",
             "category": "professional", "labels": {"accent": "tr"}},
            {"voice_id": ELEVENLABS_DEFAULT_VOICES["Matilda"], "name": "Matilda",
             "category": "premade", "labels": {"gender": "female"}},
            {"voice_id": ELEVENLABS_DEFAULT_VOICES["Brian"], "name": "Brian",
             "category": "premade", "labels": {"gender": "male", "accent": "en"}},
            {"voice_id": "FAKE_UNKNOWN_VOICE", "name": "Unknown",
             "category": "cloned", "labels": {}},
        ]
    }

    with respx.mock(base_url="https://api.elevenlabs.io") as router:
        router.get("/v1/voices").mock(return_value=Response(200, json=mock_voices))
        r = client.get("/api/tts/voices")

    assert r.status_code == 200
    body = r.json()
    returned_ids = {v["voice_id"] for v in body["voices"]}
    assert ELEVENLABS_TR_NATIVE_VOICES["Adam TR"] in returned_ids
    assert ELEVENLABS_DEFAULT_VOICES["Matilda"] in returned_ids
    # Whitelist dışı voice'lar filtrelenmeli
    assert ELEVENLABS_DEFAULT_VOICES["Brian"] not in returned_ids
    assert "FAKE_UNKNOWN_VOICE" not in returned_ids
    assert len(body["voices"]) == 2


# ── Phase 35-xi: /api/tts/usage ─────────────────────────────────────────


def test_usage_returns_503_when_api_key_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ELEVENLABS_API_KEY yoksa → 503."""
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    r = client.get("/api/tts/usage")
    assert r.status_code == 503


def test_usage_proxies_subscription_with_computed_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 35-xi: /api/tts/usage ElevenLabs subscription'ı proxy + alanlar hesaplar.

    `character_remaining` ve `percent_used` server-side hesaplanır
    (client'a hazır gelir; UI tek alan kullanır, division-by-zero
    sorununu burada handle ediyoruz).
    """
    import respx
    from httpx import Response

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")
    fake_subscription = {
        "tier": "creator",
        "character_count": 49494,
        "character_limit": 121092,
        "next_character_count_reset_unix": 1718800744,
    }

    with respx.mock(base_url="https://api.elevenlabs.io") as router:
        router.get("/v1/user/subscription").mock(
            return_value=Response(200, json=fake_subscription)
        )
        r = client.get("/api/tts/usage")

    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "ElevenLabs"
    assert body["tier"] == "creator"
    assert body["character_count"] == 49494
    assert body["character_limit"] == 121092
    assert body["character_remaining"] == 71598
    assert body["percent_used"] == 40.9  # round(100 * 49494 / 121092, 1)
    assert body["next_reset_unix"] == 1718800744


def test_usage_handles_zero_limit_safely(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """character_limit=0 (subscription unlimited?) → percent_used=0, no crash."""
    import respx
    from httpx import Response

    monkeypatch.setenv("ELEVENLABS_API_KEY", "test_key")
    with respx.mock(base_url="https://api.elevenlabs.io") as router:
        router.get("/v1/user/subscription").mock(
            return_value=Response(
                200,
                json={"tier": "free", "character_count": 0, "character_limit": 0},
            )
        )
        r = client.get("/api/tts/usage")

    assert r.status_code == 200
    assert r.json()["percent_used"] == 0.0
    assert r.json()["character_remaining"] == 0

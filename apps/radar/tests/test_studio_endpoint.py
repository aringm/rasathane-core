"""Phase 35-ii / 35-xi: Stüdyo unified UI render testleri.

/voices route'unun yeni layout'u render ettiğini doğrular:
- .studio-grid / .studio-agents / .studio-gallery class'ları HTML'de var
- function studio() Alpine bileşeni mevcut
- toggleVoicePlay inline player çağrısı var
- Eski global state (voicePicker, lastPreviewUrl) ve "Mod Atamaları" UI yok
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
    monkeypatch.setenv(
        "RASATHANE_AGENT_PROFILES_PATH",
        str(tmp_path / "agent_profiles.json"),
    )
    return TestClient(create_app())


def test_voices_page_renders_studio_layout(client: TestClient) -> None:
    """/voices yeni Stüdyo grid layout ile render edilmeli."""
    r = client.get("/voices")
    assert r.status_code == 200
    body = r.text
    assert "studio-grid" in body
    assert "studio-agents" in body
    assert "studio-gallery" in body
    assert "function studio()" in body


def test_voices_page_has_inline_test_buttons(client: TestClient) -> None:
    """Inline player (toggleVoicePlay) var; eski global lastPreviewUrl yok."""
    r = client.get("/voices")
    assert r.status_code == 200
    body = r.text
    assert "toggleVoicePlay" in body
    # Global player tek-state ARTIK YOK
    assert "lastPreviewUrl" not in body


def test_voices_page_no_mode_tabs(client: TestClient) -> None:
    """Phase 35-ii: brief/youtube mod atamaları UI'sı kaldırıldı (Phase 36'da geri)."""
    r = client.get("/voices")
    assert r.status_code == 200
    body = r.text
    assert "Mod Atamaları" not in body

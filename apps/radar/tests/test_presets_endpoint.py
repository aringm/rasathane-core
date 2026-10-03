"""Phase 36-ii: /api/tts/presets endpoints + /api/analyze/deep audio preset_id."""
from fastapi.testclient import TestClient
from rasathane_mcp.dashboard.app import create_app


def test_get_presets_returns_defaults():
    client = TestClient(create_app())
    res = client.get("/api/tts/presets")
    assert res.status_code == 200
    body = res.json()
    ids = {p["id"] for p in body["defaults"]}
    assert ids == {
        "klasik_panel",
        "hizli_brifing",
        "derin_uzman",
        "elestirel_munazara",
    }
    assert isinstance(body.get("custom"), list)
    assert isinstance(body.get("active"), list)


def test_post_preset_creates_custom(tmp_path, monkeypatch):
    """POST validated preset -> custom list'e eklenir."""
    monkeypatch.setattr(
        "llm.presets._preset_path",
        lambda: tmp_path / "audio_presets.json",
    )
    client = TestClient(create_app())
    payload = {
        "id": "my_custom",
        "name": "Benim",
        "description": "test",
        "format": "panel_3",
        "prompt_variant": "youtube_podcast_script",
        "target_minutes": [4.0, 7.0],
        "voices": {},
        "voice_settings": {},
    }
    res = client.post("/api/tts/presets", json=payload)
    assert res.status_code == 200
    res2 = client.get("/api/tts/presets")
    custom_ids = {p["id"] for p in res2.json()["custom"]}
    assert "my_custom" in custom_ids


def test_delete_default_preset_forbidden(tmp_path, monkeypatch):
    """Default preset DELETE -> 403."""
    monkeypatch.setattr(
        "llm.presets._preset_path",
        lambda: tmp_path / "audio_presets.json",
    )
    client = TestClient(create_app())
    res = client.delete("/api/tts/presets/klasik_panel")
    assert res.status_code == 403


def test_post_invalid_format_returns_422():
    client = TestClient(create_app())
    payload = {
        "id": "bad",
        "name": "B",
        "description": "x",
        "format": "BOGUS_FORMAT",
        "prompt_variant": "youtube_podcast_script",
        "target_minutes": [4.0, 7.0],
        "voices": {},
        "voice_settings": {},
    }
    res = client.post("/api/tts/presets", json=payload)
    assert res.status_code == 422

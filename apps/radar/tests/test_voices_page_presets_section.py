"""Phase 36-iv: Stüdyo Presetler section render testleri."""
from fastapi.testclient import TestClient
from rasathane_mcp.dashboard.app import create_app


def test_voices_page_renders_presets_section():
    client = TestClient(create_app())
    res = client.get("/voices")
    assert res.status_code == 200
    html = res.text
    assert "presets-section" in html
    assert "Ses Presetleri" in html


def test_voices_page_has_add_new_preset():
    client = TestClient(create_app())
    res = client.get("/voices")
    html = res.text
    assert "Yeni preset" in html
    assert "addNewPreset" in html or "addPresetModalOpen" in html

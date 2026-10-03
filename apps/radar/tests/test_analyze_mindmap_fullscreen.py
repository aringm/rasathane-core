"""Phase 36-i: Mindmap fullscreen — native API + CSS modal fallback."""
from fastapi.testclient import TestClient
from rasathane_mcp.dashboard.app import create_app


def test_analyze_page_has_native_fullscreen_handler():
    """toggleMindmapFullscreen JS method analyze sayfasında bulunur."""
    client = TestClient(create_app())
    res = client.get("/analyze")
    assert res.status_code == 200
    html = res.text
    assert "toggleMindmapFullscreen" in html
    assert "requestFullscreen" in html
    assert 'x-ref="mindmapWrapper"' in html


def test_analyze_page_has_fallback_modal_state():
    """mindmapModalFallback state var + template yalnız fallback true ise render."""
    client = TestClient(create_app())
    res = client.get("/analyze")
    html = res.text
    assert "mindmapModalFallback" in html
    assert "mindmapFullscreen && mindmapModalFallback" in html

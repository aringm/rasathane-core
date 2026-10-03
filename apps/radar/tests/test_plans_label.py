"""Phase 34-ii: /plans sayfası 'Yapılacaklar' label'ı kullanır."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_plans_page_uses_yapilacaklar_label() -> None:
    from rasathane_mcp.dashboard.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/plans")
    assert r.status_code == 200
    body = r.text
    # Yeni başlık + eyebrow
    assert "Yapılacaklar" in body
    assert "Yapılacaklar Listesi" in body
    # Eski başlık temizlenmeli
    assert "Geliştirme Planları" not in body
    # Yeni buton metni
    assert "Yeni yapılacak listesi üret" in body

"""Phase 34-ii: /canli-akis page endpoint."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_canli_akis_page_returns_200() -> None:
    from rasathane_mcp.dashboard.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/canli-akis")
    assert r.status_code == 200
    body = r.text
    assert "Canlı Akış" in body
    assert "Kaynak Akışı" in body or "Kaynaklar" in body
    assert "Sosyal Medya" in body

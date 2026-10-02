"""Phase 33-ii: /api/tags endpoint döndürdüğü canonical liste UI'ya servis eder."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_get_tags_returns_canonical_list():
    from rasathane_mcp.dashboard.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/tags")
    assert r.status_code == 200
    body = r.json()
    assert "tags" in body
    keys = [t["key"] for t in body["tags"]]
    assert "tr_hukuk" in keys
    assert "acik_kaynak_ai" in keys
    # Order korunmuş
    orders = [t["order"] for t in body["tags"]]
    assert orders == sorted(orders)

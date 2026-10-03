"""Phase 34-ii: /social-watch → /sources#sosyal 301 redirect."""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_social_watch_redirects_to_sources() -> None:
    from rasathane_mcp.dashboard.app import create_app

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as ac:
        r = await ac.get("/social-watch")
    assert r.status_code == 301
    assert r.headers["location"] == "/sources#sosyal"

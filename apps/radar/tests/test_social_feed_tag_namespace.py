"""Phase 34-ii Task B6: Sosyal medya feed UI tag namespace mismatch fix.

Bug: ``liveStreamPage()`` Alpine bileşeni article kategori key'lerini
(turk_hukuku, turkiye_ai, ...) doğrudan ``/api/social-watch/feed?tag=...``
endpoint'ine geçiyordu. Endpoint canonical tag namespace bekliyor
(tr_hukuk, tr_ai, ...). Mismatch sonucu "Türk Hukuku" filtresi her zaman
0 post döndürüyordu.

Fix: ``toSocialTag(catKey)`` mapper article kategori key'lerini canonical
tag namespace'e çevirir; eşleşmeyen anahtarlarda (muhakeme_stack vb.)
tag parametresi gönderilmez.
"""

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_canli_akis_page_has_tosocialtag_mapper() -> None:
    """Phase 34-ii: liveStreamPage'in toSocialTag mapper'ı bulunmalı."""
    from rasathane_mcp.dashboard.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/canli-akis")
    assert r.status_code == 200
    body = r.text
    # Mapper fonksiyon adı + kritik mapping entry'leri
    assert "toSocialTag(" in body, "toSocialTag mapper eksik"
    # Article kategori → canonical tag map'inin can-kritik geçişleri
    assert '"turk_hukuku":    "tr_hukuk"' in body
    assert '"turkiye_ai":     "tr_ai"' in body


@pytest.mark.asyncio
async def test_canli_akis_loadposts_uses_mapper() -> None:
    """Phase 34-ii: loadPosts() artık toSocialTag() üzerinden tag gönderir."""
    from rasathane_mcp.dashboard.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/canli-akis")
    body = r.text
    assert "this.toSocialTag(this.activeCategory)" in body
    # Eski naive activeCategory geçişi temizlenmeli
    # (params.set("tag", this.activeCategory) — direkt key geçişi)
    assert 'params.set("tag", this.activeCategory)' not in body

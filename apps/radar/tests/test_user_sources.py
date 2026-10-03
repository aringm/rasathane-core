"""Phase 15-iv: user-added sources (UI'dan ekleme/silme).

Repository helpers (add_user_source, delete_user_source) ile
endpoints (POST /api/sources, DELETE /api/sources/{id}) dahil
6 senaryo. yaml-managed koruma da pin'lenir.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from conftest import FakeResult, FakeSessionFactory, make_fake_source
from httpx import ASGITransport, AsyncClient
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def app() -> Any:
    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── POST /api/sources ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_source_returns_201_with_serialized_payload(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yeni source: 201 + serialize_source payload."""
    src = make_fake_source(name="Hukuk Genel Kurulu", category="turk_hukuku")
    src.metadata_ = {"added_by": "user"}

    async def fake_add(_session, **_kw):
        return src

    async def fake_refresh(_self, obj):  # FakeSession refresh
        return None

    # add_user_source -> session.commit + session.refresh
    monkeypatch.setattr("store.repository.add_user_source", fake_add)
    # session_factory: enter, then commit, then refresh; FakeSessionFactory provides
    # commit, but doesn't have refresh. We patch it onto the instance via FakeSession.
    fake_factory = FakeSessionFactory([FakeResult()])
    fake_factory._session.refresh = fake_refresh.__get__(fake_factory._session)  # type: ignore[attr-defined]
    monkeypatch.setattr("rasathane_mcp.dashboard.app.session_factory", fake_factory)

    async with client:
        r = await client.post(
            "/api/sources",
            json={
                "name": "Hukuk Genel Kurulu",
                "category": "turk_hukuku",
                "type": "rss",
                "url": "https://example.com/feed",
                "fetch_interval_minutes": 60,
            },
        )

    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Hukuk Genel Kurulu"
    assert body["category"] == "turk_hukuku"


@pytest.mark.asyncio
async def test_add_source_duplicate_returns_409(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(name, type, url) çakışması → 409."""
    from store.repository import DuplicateSourceError

    async def fake_add(_session, **_kw):
        raise DuplicateSourceError("source already exists: 'X'")

    monkeypatch.setattr("store.repository.add_user_source", fake_add)
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult()]),
    )

    async with client:
        r = await client.post(
            "/api/sources",
            json={
                "name": "X",
                "category": "dunya_ai",
                "type": "rss",
                "url": "https://x.com/feed",
            },
        )

    assert r.status_code == 409


@pytest.mark.asyncio
async def test_add_source_invalid_category_returns_422(client: AsyncClient) -> None:
    """Pydantic Literal: kategori unknown → 422."""
    async with client:
        r = await client.post(
            "/api/sources",
            json={
                "name": "X",
                "category": "yargi",  # not in 5 fixed categories
                "type": "rss",
                "url": "https://x.com/feed",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_add_source_invalid_type_returns_422(client: AsyncClient) -> None:
    async with client:
        r = await client.post(
            "/api/sources",
            json={
                "name": "X",
                "category": "dunya_ai",
                "type": "twitter",  # not in 4 supported types
                "url": "https://x.com/feed",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_add_source_invalid_url_returns_422(client: AsyncClient) -> None:
    """URL must start with http/https."""
    async with client:
        r = await client.post(
            "/api/sources",
            json={
                "name": "X",
                "category": "dunya_ai",
                "type": "rss",
                "url": "ftp://x.com/feed",
            },
        )
    assert r.status_code == 422


# ── DELETE /api/sources/{id} ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_user_source_returns_200(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    src_id = uuid.uuid4()

    async def fake_delete(_session, source_id):
        assert source_id == src_id

    monkeypatch.setattr("store.repository.delete_user_source", fake_delete)
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult()]),
    )

    async with client:
        r = await client.delete(f"/api/sources/{src_id}")

    assert r.status_code == 200
    assert r.json()["deleted"] is True


@pytest.mark.asyncio
async def test_delete_yaml_managed_returns_403(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yaml-managed kaynak silinemez (toggle ile sustur)."""
    from store.repository import NotUserAddedError

    async def fake_delete(_session, _source_id):
        raise NotUserAddedError("yaml-managed; edit feeds.yaml")

    monkeypatch.setattr("store.repository.delete_user_source", fake_delete)
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult()]),
    )

    async with client:
        r = await client.delete(f"/api/sources/{uuid.uuid4()}")

    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_unknown_source_returns_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_delete(_session, source_id):
        raise LookupError(f"source {source_id} not found")

    monkeypatch.setattr("store.repository.delete_user_source", fake_delete)
    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult()]),
    )

    async with client:
        r = await client.delete(f"/api/sources/{uuid.uuid4()}")

    assert r.status_code == 404

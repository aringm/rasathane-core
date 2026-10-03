"""Phase 12-iii: kütüphane CRUD endpoint'leri.

Repository helper'ları gerçek Postgres'i kullanır (test_repository.py
deseninde olduğu gibi); endpoint'ler ASGI client + monkeypatched
session_factory ile test edilir.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def app() -> Any:
    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── /api/library GET ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_library_list_empty_returns_empty_envelope(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_list(**_kw):
        return {"items": [], "offset": 0, "limit": 50, "total": 0, "has_more": False}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.list_items", fake_list)

    async with client:
        r = await client.get("/api/library")

    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_library_list_filters_by_type(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_list(**kw):
        captured.update(kw)
        return {"items": [], "offset": 0, "limit": 50, "total": 0, "has_more": False}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.list_items", fake_list)

    async with client:
        await client.get("/api/library?type=brief&q=AYM")

    assert captured["item_type"] == "brief"
    assert captured["q"] == "AYM"


@pytest.mark.asyncio
async def test_library_list_invalid_type_treated_as_all(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """type=garbage gibi bir değer → None olarak iletilir (filter yok)."""
    captured: dict[str, Any] = {}

    async def fake_list(**kw):
        captured.update(kw)
        return {"items": [], "offset": 0, "limit": 50, "total": 0, "has_more": False}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.list_items", fake_list)

    async with client:
        await client.get("/api/library?type=garbage")

    assert captured["item_type"] is None


# ── /api/library POST ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_library_save_article_returns_201(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    article_id = str(uuid.uuid4())

    async def fake_save_article(*, article_id, note):  # type: ignore[no-untyped-def]
        return {
            "id": "00000000-0000-0000-0000-000000000001",
            "saved_at": datetime.now(UTC).isoformat(),
        }

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.save_article", fake_save_article)

    async with client:
        r = await client.post(
            "/api/library",
            json={
                "item_type": "article",
                "article_id": article_id,
                "note": "X dosyası emsal",
            },
        )

    assert r.status_code == 201
    body = r.json()
    assert "id" in body
    assert "saved_at" in body


@pytest.mark.asyncio
async def test_library_save_already_saved_returns_409(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    article_id = str(uuid.uuid4())

    async def fake_save_article(*, article_id, note):  # type: ignore[no-untyped-def]
        return {"error": "already_saved", "id": "abc"}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.save_article", fake_save_article)

    async with client:
        r = await client.post(
            "/api/library",
            json={"item_type": "article", "article_id": article_id, "note": None},
        )

    assert r.status_code == 409


@pytest.mark.asyncio
async def test_library_save_article_missing_id_422(client: AsyncClient) -> None:
    async with client:
        r = await client.post("/api/library", json={"item_type": "article", "note": "x"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_library_save_deep_analysis_returns_201(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Phase 17-v: deep_analysis tipi kütüphaneye kaydedilebilir."""
    job_id = "0123456789abcdef"

    async def fake_save(*, job_id, note, archive_root):  # type: ignore[no-untyped-def]
        return {
            "id": "00000000-0000-0000-0000-000000000077",
            "saved_at": datetime.now(UTC).isoformat(),
        }

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.save_deep_analysis", fake_save)

    async with client:
        r = await client.post(
            "/api/library",
            json={
                "item_type": "deep_analysis",
                "deep_analysis_job_id": job_id,
                "note": "Test analiz notu",
            },
        )

    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "00000000-0000-0000-0000-000000000077"


@pytest.mark.asyncio
async def test_library_save_deep_analysis_invalid_job_id_422(client: AsyncClient) -> None:
    """job_id 16-hex değil → pydantic pattern reject."""
    async with client:
        r = await client.post(
            "/api/library",
            json={"item_type": "deep_analysis", "deep_analysis_job_id": "not-hex"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_library_save_deep_analysis_missing_job_id_422(client: AsyncClient) -> None:
    """deep_analysis_job_id eksik → 422 dispatcher tarafından."""
    async with client:
        r = await client.post("/api/library", json={"item_type": "deep_analysis"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_library_save_deep_analysis_not_found_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """deep_not_found result → 404."""

    async def fake_save(*, job_id, note, archive_root):  # type: ignore[no-untyped-def]
        return {"error": "deep_not_found"}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.save_deep_analysis", fake_save)

    async with client:
        r = await client.post(
            "/api/library",
            json={"item_type": "deep_analysis", "deep_analysis_job_id": "ffeeddccbbaa9988"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_library_save_brief_invalid_date_422(client: AsyncClient) -> None:
    async with client:
        r = await client.post(
            "/api/library",
            json={"item_type": "brief", "brief_date": "not-a-date"},
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_library_save_unknown_item_type_422(client: AsyncClient) -> None:
    async with client:
        r = await client.post("/api/library", json={"item_type": "garbage"})
    assert r.status_code == 422


# ── /api/library/{id} DELETE + PATCH ────────────────────────────────────


@pytest.mark.asyncio
async def test_library_delete_404_when_not_found(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_delete(_id):
        return False

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.delete_item", fake_delete)

    async with client:
        r = await client.delete(f"/api/library/{uuid.uuid4()}")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_library_patch_note_updates(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    item_id = uuid.uuid4()

    async def fake_update(_id, note):
        return {"id": str(item_id), "note": note}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.update_note", fake_update)

    async with client:
        r = await client.patch(f"/api/library/{item_id}", json={"note": "yeni not"})

    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "yeni not"


# ── /api/articles/{id}/summary/long ─────────────────────────────────────


@pytest.mark.asyncio
async def test_long_summary_404_for_unknown_article(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bilinmeyen id → 404 article_not_found."""
    from conftest import FakeResult, FakeSessionFactory

    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult(scalar_value=None)]),
    )

    async with client:
        r = await client.post(f"/api/articles/{uuid.uuid4()}/summary/long")

    assert r.status_code == 404


# ── Phase 19-i: per-article short summary on-demand ──────────────────


@pytest.mark.asyncio
async def test_short_summary_404_for_unknown_article(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bilinmeyen id → 404 article_not_found (mirror long endpoint)."""
    from conftest import FakeResult, FakeSessionFactory

    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult(scalar_value=None)]),
    )

    async with client:
        r = await client.post(f"/api/articles/{uuid.uuid4()}/summary/short")

    assert r.status_code == 404


@pytest.mark.asyncio
async def test_short_summary_returns_cached_when_already_translated(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """summary_tr_short doluysa CLI çağrılmaz, cache döner."""
    from unittest.mock import MagicMock

    from conftest import FakeResult, FakeSessionFactory

    article = MagicMock()
    article.summary_tr_short = "Cached Türkçe özet."
    article.id = uuid.uuid4()

    monkeypatch.setattr(
        "rasathane_mcp.dashboard.app.session_factory",
        FakeSessionFactory([FakeResult(scalar_value=article)]),
    )

    cli_called = False

    async def fake_cli(*_a, **_kw):
        nonlocal cli_called
        cli_called = True
        return "should not be called"

    monkeypatch.setattr("llm.translate._generate_short_with_fallback", fake_cli)

    async with client:
        r = await client.post(f"/api/articles/{article.id}/summary/short")

    assert r.status_code == 200
    body = r.json()
    assert body["cached"] is True
    assert body["summary_tr_short"] == "Cached Türkçe özet."
    assert cli_called is False  # Cache hit guard


# ── Phase 17-v: core_library.save_deep_analysis filesystem ───────────


@pytest.mark.asyncio
async def test_save_deep_analysis_returns_not_found_when_job_dir_missing(
    tmp_path: Any,
) -> None:
    """archive/deep/{job_id}/ yoksa → error: deep_not_found."""
    from rasathane_mcp.core import library as core_library

    out = await core_library.save_deep_analysis(
        job_id="ffffffffffffffff", note=None, archive_root=tmp_path
    )
    assert out == {"error": "deep_not_found"}


@pytest.mark.asyncio
async def test_save_deep_analysis_returns_not_found_when_summary_missing(
    tmp_path: Any,
) -> None:
    """Dizin var ama summary.md yok → error: deep_not_found."""
    from rasathane_mcp.core import library as core_library

    job_id = "abc1234567890def"
    target = tmp_path / "deep" / job_id
    target.mkdir(parents=True)
    # transcript var ama summary yok
    (target / "transcript.md").write_text("transkript", encoding="utf-8")

    out = await core_library.save_deep_analysis(job_id=job_id, note=None, archive_root=tmp_path)
    assert out == {"error": "deep_not_found"}


# ── Phase 13: /api/brief library state ─────────────────────────────────


@pytest.mark.asyncio
async def test_brief_endpoint_includes_library_state_when_not_saved(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief mevcut + kütüphanede değil → in_library False, library_item_id None."""

    def fake_load_brief(**_kw):
        return {
            "date": "2026-05-07",
            "top_brief": "## Brief\n\nİçerik...",
            "category_files": [],
            "has_mindmap": False,
            "generating": False,
            "generated_at": "2026-05-07T08:00:00+00:00",
            "last_error": None,
        }

    async def fake_lookup(_brief_date):
        return None

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_brief.load_brief", fake_load_brief)
    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.lookup_brief_status", fake_lookup)

    async with client:
        r = await client.get("/api/brief")

    assert r.status_code == 200
    body = r.json()
    assert body["in_library"] is False
    assert body["library_item_id"] is None


@pytest.mark.asyncio
async def test_brief_endpoint_includes_library_state_when_saved(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief mevcut + kütüphanede → in_library True, library_item_id dolu."""
    item_id = "00000000-0000-0000-0000-000000000099"

    def fake_load_brief(**_kw):
        return {
            "date": "2026-05-07",
            "top_brief": "## Brief\n\n…",
            "category_files": [],
            "has_mindmap": False,
            "generating": False,
            "generated_at": "2026-05-07T08:00:00+00:00",
            "last_error": None,
        }

    async def fake_lookup(_brief_date):
        return {"library_item_id": item_id, "saved_at": "2026-05-07T09:00:00+00:00"}

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_brief.load_brief", fake_load_brief)
    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.lookup_brief_status", fake_lookup)

    async with client:
        r = await client.get("/api/brief")

    assert r.status_code == 200
    body = r.json()
    assert body["in_library"] is True
    assert body["library_item_id"] == item_id


@pytest.mark.asyncio
async def test_brief_endpoint_skips_library_state_on_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief yok (error path) → lookup hiç çağrılmaz, payload olduğu gibi."""
    lookup_called = False

    def fake_load_brief(**_kw):
        return {"error": "no briefs found in archive/"}

    async def fake_lookup(_brief_date):
        nonlocal lookup_called
        lookup_called = True
        return None

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_brief.load_brief", fake_load_brief)
    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.lookup_brief_status", fake_lookup)

    async with client:
        r = await client.get("/api/brief")

    assert r.status_code == 200
    body = r.json()
    assert "error" in body
    assert "in_library" not in body
    assert lookup_called is False


@pytest.mark.asyncio
async def test_brief_endpoint_skips_library_state_when_generating(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generation lockfile varsa → bookmark state göstermenin anlamı yok."""
    lookup_called = False

    def fake_load_brief(**_kw):
        return {
            "date": "2026-05-07",
            "generating": True,
            "started_at": "2026-05-07T08:00:00+00:00",
            "elapsed_sec": 12,
            "top_brief": None,
        }

    async def fake_lookup(_brief_date):
        nonlocal lookup_called
        lookup_called = True
        return None

    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_brief.load_brief", fake_load_brief)
    monkeypatch.setattr("rasathane_mcp.dashboard.app.core_library.lookup_brief_status", fake_lookup)

    async with client:
        r = await client.get("/api/brief")

    assert r.status_code == 200
    body = r.json()
    assert body["generating"] is True
    assert "in_library" not in body
    assert lookup_called is False


# ── Phase 22-iii: brief audio endpoint ───────────────────────────────


@pytest.mark.asyncio
async def test_brief_audio_returns_404_when_brief_missing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """archive/{date}/00-brief.md yoksa → 404."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", _Path(tmp))
        async with client:
            r = await client.post("/api/brief/audio", json={"date": "2026-05-08"})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_brief_audio_returns_already_exists_when_mp3_cached(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """00-brief.mp3 zaten varsa → cache hit response."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        date = "2026-05-08"
        target = _Path(tmp) / date
        target.mkdir(parents=True)
        (target / "00-brief.md").write_text("brief", encoding="utf-8")
        (target / "00-brief.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 50)

        monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", _Path(tmp))
        async with client:
            r = await client.post("/api/brief/audio", json={"date": date})
        # 202 status_code default (decorator), already_exists path da aynı
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "already_exists"
        assert body["audio_url"].endswith("/00-brief.mp3")


# ── Phase 28-iv: kütüphane sesli özet endpoint'leri ──────────────────


@pytest.mark.asyncio
async def test_library_audio_status_not_generated_when_no_mp3(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """archive/library/{id}.mp3 yoksa → not_generated."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", _Path(tmp))
        item_id = uuid.uuid4()
        async with client:
            r = await client.get(f"/api/library/{item_id}/audio")
        assert r.status_code == 200
        assert r.json()["status"] == "not_generated"


@pytest.mark.asyncio
async def test_library_audio_status_done_when_mp3_present(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """archive/library/{id}.mp3 varsa → done + audio_url."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        item_id = uuid.uuid4()
        lib_dir = _Path(tmp) / "library"
        lib_dir.mkdir()
        (lib_dir / f"{item_id}.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 50)
        monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", _Path(tmp))
        async with client:
            r = await client.get(f"/api/library/{item_id}/audio")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "done"
        assert body["audio_url"].endswith(f"{item_id}.mp3")


@pytest.mark.asyncio
async def test_library_audio_status_in_progress_when_lock_present(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lockfile varsa → in_progress."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        item_id = uuid.uuid4()
        lib_dir = _Path(tmp) / "library"
        lib_dir.mkdir()
        (lib_dir / f".{item_id}.lock").write_text("{}", encoding="utf-8")
        monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", _Path(tmp))
        async with client:
            r = await client.get(f"/api/library/{item_id}/audio")
        assert r.status_code == 200
        assert r.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_library_audio_post_returns_already_exists_when_cached(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mp3 varsa POST → 202 already_exists (background task tetiklenmez)."""
    import tempfile
    from pathlib import Path as _Path

    with tempfile.TemporaryDirectory() as tmp:
        item_id = uuid.uuid4()
        lib_dir = _Path(tmp) / "library"
        lib_dir.mkdir()
        (lib_dir / f"{item_id}.mp3").write_bytes(b"\xff\xfb" + b"\x00" * 50)
        monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", _Path(tmp))
        # Generic library item DB'de yoksa 404 — fake item return etsin

        async def fake_get(_session, _item_id):
            class _Item:
                pass

            return _Item()

        monkeypatch.setattr("store.repository.get_library_item", fake_get)
        async with client:
            r = await client.post(f"/api/library/{item_id}/audio")
        assert r.status_code == 202
        body = r.json()
        assert body["status"] == "already_exists"
        assert body["audio_url"].endswith(".mp3")

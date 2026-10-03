"""Phase 19-v: kütüphane → plan + to-do list tests.

generate_plan filesystem-authoritative; toggle_todo plan.md'i in-place
düzenler. Backend logic + endpoints test edilir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from rasathane_mcp.core import plans as core_plans
from rasathane_mcp.dashboard.app import create_app


@pytest.fixture
def app() -> Any:
    return create_app()


@pytest.fixture
async def client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── compute_plan_id + lookup_status ──────────────────────────────────


def test_compute_plan_id_deterministic() -> None:
    a = core_plans.compute_plan_id(["x", "y", "z"])
    b = core_plans.compute_plan_id(["z", "x", "y"])  # different order
    assert a == b  # sorted internally
    assert len(a) == 16


def test_lookup_status_not_found_when_dir_missing(tmp_path: Path) -> None:
    out = core_plans.lookup_status(archive_root=tmp_path, plan_id="0123456789abcdef")
    assert out == {"plan_id": "0123456789abcdef", "status": "not_found"}


def test_lookup_status_done_when_plan_md_exists(tmp_path: Path) -> None:
    plan_id = "abcdef0123456789"
    target = tmp_path / "plans" / plan_id
    target.mkdir(parents=True)
    (target / "plan.md").write_text("# Plan\n\n- [ ] yapılacak", encoding="utf-8")

    out = core_plans.lookup_status(archive_root=tmp_path, plan_id=plan_id)
    assert out["status"] == "done"
    assert "yapılacak" in out["plan_md"]


# ── toggle_todo ───────────────────────────────────────────────────────


def test_toggle_todo_unchecked_to_checked(tmp_path: Path) -> None:
    plan_id = "1111222233334444"
    target = tmp_path / "plans" / plan_id
    target.mkdir(parents=True)
    plan_md = "# Plan\n\n## Yapılacaklar\n- [ ] ilk madde\n- [ ] ikinci madde"
    (target / "plan.md").write_text(plan_md, encoding="utf-8")

    # 3. satır (0-indexed) "- [ ] ilk madde"
    out = core_plans.toggle_todo(archive_root=tmp_path, plan_id=plan_id, line_index=3)
    assert out.get("ok") is True
    assert "[x]" in out["line"]

    # Dosyada da değişti mi?
    new = (target / "plan.md").read_text(encoding="utf-8")
    assert "- [x] ilk madde" in new
    assert "- [ ] ikinci madde" in new  # diğer satır değişmemiş


def test_toggle_todo_checked_to_unchecked(tmp_path: Path) -> None:
    plan_id = "5555666677778888"
    target = tmp_path / "plans" / plan_id
    target.mkdir(parents=True)
    (target / "plan.md").write_text("- [x] tamamlandı", encoding="utf-8")

    out = core_plans.toggle_todo(archive_root=tmp_path, plan_id=plan_id, line_index=0)
    assert out.get("ok") is True
    assert "[ ]" in out["line"]


def test_toggle_todo_returns_error_on_non_checkbox_line(tmp_path: Path) -> None:
    plan_id = "9999aaaabbbbcccc"
    target = tmp_path / "plans" / plan_id
    target.mkdir(parents=True)
    (target / "plan.md").write_text("# Başlık\n\nDüz paragraf", encoding="utf-8")

    out = core_plans.toggle_todo(archive_root=tmp_path, plan_id=plan_id, line_index=0)
    assert out.get("error") == "not_a_checkbox"


def test_toggle_todo_invalid_line_index(tmp_path: Path) -> None:
    plan_id = "deadbeef00000000"
    target = tmp_path / "plans" / plan_id
    target.mkdir(parents=True)
    (target / "plan.md").write_text("- [ ] tek madde", encoding="utf-8")

    out = core_plans.toggle_todo(archive_root=tmp_path, plan_id=plan_id, line_index=999)
    assert out.get("error") == "invalid_line"


# ── endpoints ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plans_get_invalid_id_returns_404(client: AsyncClient) -> None:
    async with client:
        r = await client.get("/api/plans/notavalidplanid")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_plans_post_returns_202(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Background task'a ekler, hemen 202 dön."""
    called = {"n": 0}

    async def fake_generate(**_kw):
        called["n"] += 1
        return {"plan_id": "x", "status": "done"}

    monkeypatch.setattr("rasathane_mcp.core.plans.generate_plan", fake_generate)

    async with client:
        r = await client.post("/api/plans", json={"plan_title": "Test"})

    assert r.status_code == 202
    assert r.json()["status"] == "queued"


@pytest.mark.asyncio
async def test_plan_toggle_todo_endpoint(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_toggle(*, archive_root, plan_id, line_index):
        return {"ok": True, "line": "- [x] yapıldı"}

    monkeypatch.setattr("rasathane_mcp.core.plans.toggle_todo", fake_toggle)

    async with client:
        r = await client.patch("/api/plans/0123456789abcdef/todo", json={"line_index": 5})

    assert r.status_code == 200
    assert "[x]" in r.json()["line"]


@pytest.mark.asyncio
async def test_plan_toggle_todo_missing_line_index_returns_422(
    client: AsyncClient,
) -> None:
    async with client:
        r = await client.patch("/api/plans/0123456789abcdef/todo", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_plans_list_returns_empty_when_no_plans(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """archive/plans/ yoksa → empty list."""
    monkeypatch.setattr("rasathane_mcp.dashboard.app.ARCHIVE_ROOT", tmp_path)

    async with client:
        r = await client.get("/api/plans")

    assert r.status_code == 200
    assert r.json()["plans"] == []

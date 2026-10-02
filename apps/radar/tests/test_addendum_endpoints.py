"""Phase 36-iii: addendum API endpoint smoke testleri."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from rasathane_mcp.dashboard.app import create_app


def test_get_addendum_index_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("rasathane_mcp.core.addendum.DEEP_DIR", tmp_path)
    job_id = "test_job"
    (tmp_path / job_id).mkdir()
    client = TestClient(create_app())
    res = client.get(f"/api/analyze/deep/{job_id}/addendum")
    assert res.status_code == 200
    assert res.json() == {"entries": []}


def test_post_angles_returns_array(tmp_path, monkeypatch):
    monkeypatch.setattr("rasathane_mcp.core.addendum.DEEP_DIR", tmp_path)
    job_id = "test_job2"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "summary.md").write_text("özet", encoding="utf-8")
    fake = '[{"slug":"hukuki","title":"Hukuki","why":"x"}]'
    with patch(
        "rasathane_mcp.core.addendum.synthesize_with_claude",
        new=AsyncMock(return_value=fake),
    ):
        client = TestClient(create_app())
        res = client.post(f"/api/analyze/deep/{job_id}/addendum/angles")
    assert res.status_code == 200
    body = res.json()
    assert len(body["angles"]) == 1
    assert body["angles"][0]["slug"] == "hukuki"


def test_post_addendum_freeform_creates_entry(tmp_path, monkeypatch):
    monkeypatch.setattr("rasathane_mcp.core.addendum.DEEP_DIR", tmp_path)

    async def fake_tag_ctx(tags, limit=5):
        return ""

    monkeypatch.setattr(
        "rasathane_mcp.core.addendum._fetch_tag_context", fake_tag_ctx
    )
    job_id = "test_job3"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "summary.md").write_text("özet", encoding="utf-8")
    with patch(
        "rasathane_mcp.core.addendum.synthesize_with_claude",
        new=AsyncMock(return_value="analiz metni"),
    ):
        client = TestClient(create_app())
        res = client.post(
            f"/api/analyze/deep/{job_id}/addendum",
            json={
                "type": "freeform",
                "question": "Test soru",
                "tags": ["tr_hukuk"],
            },
        )
    assert res.status_code == 200
    assert res.json()["entry"]["type"] == "freeform"


def test_delete_addendum_removes(tmp_path, monkeypatch):
    monkeypatch.setattr("rasathane_mcp.core.addendum.DEEP_DIR", tmp_path)
    from rasathane_mcp.core import addendum

    job_id = "test_job4"
    (tmp_path / job_id).mkdir()
    (tmp_path / job_id / "addendum_test.md").write_text("x", encoding="utf-8")
    addendum.save_index(job_id, [{"slug": "test", "type": "angle", "title": "T"}])
    client = TestClient(create_app())
    res = client.delete(f"/api/analyze/deep/{job_id}/addendum/test")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_get_related_articles_endpoint_returns_sources(tmp_path, monkeypatch):
    async def fake_related(job_id, limit=5):
        return []

    monkeypatch.setattr(
        "rasathane_mcp.core.articles.find_related_to_deep_job",
        fake_related,
    )
    client = TestClient(create_app())
    res = client.get("/api/articles/related?job_id=test&limit=5")
    assert res.status_code == 200
    assert "sources" in res.json()

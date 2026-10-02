"""Hourly cron: sync sonrası translate_short_pending çağrılır mı?"""

from __future__ import annotations

import pytest
from worker.main import _hourly_sync_job


async def test_hourly_sync_job_calls_translate_after_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """sync_all_enabled → translate_short_pending sırası korunur."""
    call_order: list[str] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    fake_factory = lambda: FakeSession()  # noqa: E731

    async def fake_sync(_session):
        call_order.append("sync")
        return {"src1": 5}

    async def fake_translate(_session, *, limit: int):
        call_order.append(f"translate(limit={limit})")
        return 5, 0

    monkeypatch.setattr("worker.main.session_factory", fake_factory)
    monkeypatch.setattr("worker.main.sync_all_enabled", fake_sync)
    monkeypatch.setattr("worker.main.translate_short_pending", fake_translate)

    await _hourly_sync_job()

    assert call_order == ["sync", "translate(limit=100)"]


async def test_hourly_sync_job_continues_if_translate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Translate hatası sync'i invalide etmez (zaten committed)."""

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    fake_factory = lambda: FakeSession()  # noqa: E731

    async def fake_sync(_session):
        return {"src1": 5}

    async def fake_translate_fails(*_args, **_kwargs):
        raise RuntimeError("gemini outage")

    monkeypatch.setattr("worker.main.session_factory", fake_factory)
    monkeypatch.setattr("worker.main.sync_all_enabled", fake_sync)
    monkeypatch.setattr("worker.main.translate_short_pending", fake_translate_fails)

    # Should NOT raise — translation failure is logged-and-swallowed
    await _hourly_sync_job()


# ── Phase 20-ii: opt-in auto-brief ───────────────────────────────────


async def test_hourly_sync_skips_auto_brief_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (RASATHANE_AUTO_BRIEF unset) → generate_brief çağrılmaz."""

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    async def fake_sync(_session):
        return {"src1": 5}

    async def fake_translate(_session, *, limit: int):
        return 5, 0

    monkeypatch.setattr("worker.main.session_factory", lambda: FakeSession())
    monkeypatch.setattr("worker.main.sync_all_enabled", fake_sync)
    monkeypatch.setattr("worker.main.translate_short_pending", fake_translate)
    monkeypatch.delenv("RASATHANE_AUTO_BRIEF", raising=False)

    brief_called = False

    async def fake_generate(*_a, **_kw):
        nonlocal brief_called
        brief_called = True
        return {"date": "2026-05-07"}

    monkeypatch.setattr("rasathane_mcp.core.brief.generate_brief", fake_generate)

    await _hourly_sync_job()

    assert brief_called is False  # opt-in: env yoksa skip


async def test_hourly_sync_calls_auto_brief_when_env_truthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RASATHANE_AUTO_BRIEF=1 → generate_brief tetiklenir."""

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    async def fake_sync(_session):
        return {"src1": 5}

    async def fake_translate(_session, *, limit: int):
        return 5, 0

    monkeypatch.setattr("worker.main.session_factory", lambda: FakeSession())
    monkeypatch.setattr("worker.main.sync_all_enabled", fake_sync)
    monkeypatch.setattr("worker.main.translate_short_pending", fake_translate)
    monkeypatch.setenv("RASATHANE_AUTO_BRIEF", "1")

    brief_called = False

    async def fake_generate(_session, *, archive_root, force):
        nonlocal brief_called
        brief_called = True
        return {"date": "2026-05-07", "started_at": "now"}

    monkeypatch.setattr("rasathane_mcp.core.brief.generate_brief", fake_generate)

    await _hourly_sync_job()

    assert brief_called is True


async def test_hourly_sync_auto_brief_swallows_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """already_exists → log info, exception fırlatma."""

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

    async def fake_sync(_session):
        return {"src1": 5}

    async def fake_translate(_session, *, limit: int):
        return 5, 0

    monkeypatch.setattr("worker.main.session_factory", lambda: FakeSession())
    monkeypatch.setattr("worker.main.sync_all_enabled", fake_sync)
    monkeypatch.setattr("worker.main.translate_short_pending", fake_translate)
    monkeypatch.setenv("RASATHANE_AUTO_BRIEF", "1")

    async def fake_generate(*_a, **_kw):
        return {"error": "already_exists", "generated_at": "earlier"}

    monkeypatch.setattr("rasathane_mcp.core.brief.generate_brief", fake_generate)

    # Should not raise
    await _hourly_sync_job()

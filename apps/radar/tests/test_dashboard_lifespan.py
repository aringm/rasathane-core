"""Tests for the FastMCP dashboard lifespan.

Covers the three behaviours that matter for PR-1:
    1. Free port → spin up uvicorn, /api/health is reachable, port is
       freed on lifespan exit.
    2. Port already taken → attach (no second uvicorn), still report
       the URL so MCP tools and tests can see it.
    3. ``RASATHANE_NO_BROWSER`` truthy → never call ``webbrowser.open``.

Each test grabs an OS-assigned free port to avoid collisions when the
suite runs in parallel or alongside a live dashboard.
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

import httpx
import pytest
from rasathane_mcp.dashboard import lifespan as lifespan_mod
from rasathane_mcp.dashboard.lifespan import (
    _browser_suppressed,
    _resolve_port,
    dashboard_lifespan,
)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


# ── env helpers ────────────────────────────────────────────────────────


def test_resolve_port_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RASATHANE_PORT", raising=False)
    assert _resolve_port() == 8765


def test_resolve_port_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RASATHANE_PORT", "9123")
    assert _resolve_port() == 9123


def test_resolve_port_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RASATHANE_PORT", "not-a-number")
    assert _resolve_port() == 8765


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1", True),
        ("true", True),
        ("YES", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_browser_suppressed(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("RASATHANE_NO_BROWSER", value)
    assert _browser_suppressed() is expected


# ── lifespan integration ───────────────────────────────────────────────


async def test_lifespan_starts_server_and_serves_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")

    async with dashboard_lifespan(None) as ctx:
        assert ctx["owned"] is True
        assert ctx["dashboard_url"] == f"http://127.0.0.1:{port}"

        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"http://127.0.0.1:{port}/api/health")
            assert r.status_code == 200
            assert r.json() == {"status": "ok", "service": "rasathane-dashboard"}

            root = await client.get(f"http://127.0.0.1:{port}/")
            assert root.status_code == 200
            assert "Rasathane" in root.text

    # Port should be released after teardown — bind succeeds.
    await asyncio.sleep(0.05)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.close()


async def test_lifespan_attaches_when_port_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")

    async def _noop(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    holder = await asyncio.start_server(_noop, "127.0.0.1", port)
    try:
        async with dashboard_lifespan(None) as ctx:
            assert ctx["owned"] is False
            assert ctx["dashboard_url"] == f"http://127.0.0.1:{port}"
    finally:
        holder.close()
        await holder.wait_closed()


async def test_browser_open_suppressed_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")

    calls: list[Any] = []

    def _spy(*args: Any, **kwargs: Any) -> bool:
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(lifespan_mod.webbrowser, "open", _spy)

    async with dashboard_lifespan(None):
        pass

    assert calls == []


async def test_browser_open_invoked_when_not_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.delenv("RASATHANE_NO_BROWSER", raising=False)

    calls: list[str] = []

    def _spy(url: str, *_args: Any, **_kwargs: Any) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr(lifespan_mod.webbrowser, "open", _spy)

    async with dashboard_lifespan(None):
        pass

    assert calls == [f"http://127.0.0.1:{port}"]


async def test_attach_path_does_not_open_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Port zaten LISTENING ise yeni sekme açma — owner-only davranış.

    Senaryo: Claude Desktop'un MCP'si zaten 8765'i bind etmiş; Claude
    Code 2. session olarak aynı MCP'yi spawn ediyor. Sahip değiliz,
    sekmeyi tekrar açmamalıyız.
    """
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.delenv("RASATHANE_NO_BROWSER", raising=False)

    calls: list[str] = []

    def _spy(url: str, *_args: Any, **_kwargs: Any) -> bool:
        calls.append(url)
        return True

    monkeypatch.setattr(lifespan_mod.webbrowser, "open", _spy)

    async def _noop(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    holder = await asyncio.start_server(_noop, "127.0.0.1", port)
    try:
        async with dashboard_lifespan(None) as ctx:
            assert ctx["owned"] is False
    finally:
        holder.close()
        await holder.wait_closed()

    assert calls == []


# ── Phase 16-i: opt-in cron scheduler ────────────────────────────────


async def test_cron_off_by_default_lifespan_reports_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (env unset) → cron started=False, dashboard yine yaşar."""
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")
    monkeypatch.delenv("RASATHANE_ENABLE_CRON", raising=False)

    async with dashboard_lifespan(None) as ctx:
        assert ctx["cron"] is False


async def test_cron_starts_when_env_truthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RASATHANE_ENABLE_CRON=1 → scheduler started, ctx['cron']=True.

    AsyncIOScheduler import edilirken job spec'i alır; gerçek
    `_hourly_sync_job` çağrılmaz çünkü interval=1h ve test 1 sn'den kısa.
    """
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")
    monkeypatch.setenv("RASATHANE_ENABLE_CRON", "1")

    async with dashboard_lifespan(None) as ctx:
        assert ctx["cron"] is True


async def test_cron_disabled_via_falsy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RASATHANE_ENABLE_CRON=0 (explicit off) → cron started=False."""
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")
    monkeypatch.setenv("RASATHANE_ENABLE_CRON", "0")

    async with dashboard_lifespan(None) as ctx:
        assert ctx["cron"] is False


async def test_cron_attached_dashboard_does_not_double_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Başka bir process zaten 8765'te → bu lifespan attach yapar, cron
    BAŞLATMAZ (yoksa çift sync). RASATHANE_ENABLE_CRON=1 olsa da."""
    port = _free_port()
    monkeypatch.setenv("RASATHANE_PORT", str(port))
    monkeypatch.setenv("RASATHANE_NO_BROWSER", "1")
    monkeypatch.setenv("RASATHANE_ENABLE_CRON", "1")

    async def _noop(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    holder = await asyncio.start_server(_noop, "127.0.0.1", port)
    try:
        async with dashboard_lifespan(None) as ctx:
            assert ctx["owned"] is False
            assert ctx["cron"] is False
    finally:
        holder.close()
        await holder.wait_closed()

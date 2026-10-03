"""FastMCP lifespan that boots the dashboard alongside the stdio MCP server.

Mirrors Serena's pattern: when Claude Desktop spawns the MCP process,
the lifespan starts a uvicorn task on ``127.0.0.1:RASATHANE_PORT`` (default
8765) and — unless suppressed — opens the user's default browser at it.
The server task is shut down gracefully when Claude Desktop stops the
MCP process (lifespan exit).

Single-instance / owner-only browser behaviour: if another Rasathane MCP
process is already serving the dashboard (port in use), we silently
attach without spawning a second server and without re-opening a tab.
Only the port owner — the first lifespan that finds the port free and
binds it — opens the browser. This avoids ``EADDRINUSE`` collisions
when multiple MCP clients (Claude Desktop + Claude Code) spawn
concurrently, and prevents duplicate tabs on every subsequent attach.

Env knobs:
    ``RASATHANE_PORT``         — override port (default 8765).
    ``RASATHANE_NO_BROWSER``   — set to ``1``/``true`` to keep the
                                 dashboard reachable but suppress the
                                 auto-launch tab.
    ``RASATHANE_ENABLE_CRON``  — set to ``1`` to run the hourly RSS sync
                                 + translate scheduler inside this MCP
                                 process (Phase 16-i). Default off so the
                                 standalone ``apps/worker`` daemon stays
                                 canonical; set to ``1`` for single-
                                 process deployments where Claude Desktop
                                 spawning the MCP is the only entry point.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import webbrowser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
import uvicorn

from rasathane_mcp.dashboard.app import create_app

log = structlog.get_logger()

DEFAULT_PORT = 8765
PORT_PROBE_TIMEOUT_S = 0.3
SERVER_READY_POLL_S = 0.05
SERVER_READY_TIMEOUT_S = 5.0
CRON_INTERVAL_HOURS = 1
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _resolve_port() -> int:
    raw = os.environ.get("RASATHANE_PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        return int(raw)
    except ValueError:
        log.warning("dashboard.port.invalid", value=raw, fallback=DEFAULT_PORT)
        return DEFAULT_PORT


def _browser_suppressed() -> bool:
    return os.environ.get("RASATHANE_NO_BROWSER", "").strip().lower() in _TRUTHY


def _cron_enabled() -> bool:
    """Phase 16-i: opt-in via env. Default off (apps/worker is canonical)."""
    return os.environ.get("RASATHANE_ENABLE_CRON", "").strip().lower() in _TRUTHY


def _start_cron_if_enabled() -> Any | None:
    """Build + start an APScheduler if RASATHANE_ENABLE_CRON is truthy.

    Returns the scheduler (caller calls ``shutdown(wait=True)``) or None.
    Imports are lazy so the lifespan import path stays light when cron
    is off (the default).
    """
    if not _cron_enabled():
        return None

    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from worker.main import _hourly_sync_job

    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(
        _hourly_sync_job,
        trigger="interval",
        hours=CRON_INTERVAL_HOURS,
        id="rss_sync_hourly",
        coalesce=True,
        max_instances=1,
        # Phase 16-i: ilk run lifespan başlangıcında 30 sn sonra —
        # cold-start senkronu için ki kullanıcı dashboard açtığında
        # akış sürekli güncel görünsün.
        next_run_time=None,
    )
    scheduler.start()
    log.info("cron.started", interval_hours=CRON_INTERVAL_HOURS)
    return scheduler


async def _is_port_open(port: int) -> bool:
    """True if *something* is already accepting connections on ``port``.

    Uses asyncio sockets so it composes with the lifespan's event loop
    and never blocks the MCP transport.
    """
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", port),
            timeout=PORT_PROBE_TIMEOUT_S,
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    return True


async def _open_browser(url: str) -> None:
    """Fire-and-forget browser launch. ``webbrowser.open`` may exec a child process; run off-thread."""
    await asyncio.to_thread(webbrowser.open, url, 2)


async def _wait_until_started(server: uvicorn.Server) -> None:
    # uvicorn exposes a sync ``started`` bool — no event to await on, so we poll.
    # ASYNC110 wants asyncio.Event, but that would require monkey-patching
    # uvicorn internals; a 50ms tick is fine for a lifespan startup probe.
    while not server.started:  # noqa: ASYNC110
        await asyncio.sleep(SERVER_READY_POLL_S)


@asynccontextmanager
async def dashboard_lifespan(_server: Any) -> AsyncIterator[dict[str, Any]]:
    """Start the dashboard (or attach to an existing one) for the MCP session.

    Yields a small context dict so FastMCP tools can introspect the
    dashboard URL via ``ctx.lifespan_context`` if needed.
    """
    port = _resolve_port()
    url = f"http://127.0.0.1:{port}"

    # Phase 16-i: cron yalnız opt-in. Dashboard zaten başka bir process'te
    # çalışıyorsa cron'u burada başlatmıyoruz — çift başlatma çift sync olur.
    cron_scheduler: Any | None = None

    if await _is_port_open(port):
        log.info("dashboard.attach.existing", port=port, url=url)
        # Owner-only browser open: the process that bound the port already
        # opened the tab. Subsequent attaches (e.g. Claude Code spawning a
        # second MCP while Claude Desktop's is already up) stay silent.
        yield {"dashboard_url": url, "owned": False, "cron": False}
        return

    config = uvicorn.Config(
        create_app(),
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve(), name="rasathane-dashboard")

    try:
        await asyncio.wait_for(_wait_until_started(server), timeout=SERVER_READY_TIMEOUT_S)
    except TimeoutError:
        log.error("dashboard.start.timeout", port=port)
        server.should_exit = True
        with contextlib.suppress(Exception):
            await serve_task
        raise

    log.info("dashboard.start.ok", port=port, url=url)
    if not _browser_suppressed():
        await _open_browser(url)

    # Phase 16-i: cron başlat (opt-in). dashboard process owner olduğu için
    # çift başlatma riski yok. Hata olursa dashboard yine yaşar — cron
    # opsiyonel bir feature.
    try:
        cron_scheduler = _start_cron_if_enabled()
    except Exception as e:
        log.error("cron.start.failed", err=str(e)[:200])
        cron_scheduler = None

    try:
        yield {
            "dashboard_url": url,
            "owned": True,
            "cron": cron_scheduler is not None,
        }
    finally:
        if cron_scheduler is not None:
            with contextlib.suppress(Exception):
                cron_scheduler.shutdown(wait=False)
            log.info("cron.stop")
        server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await serve_task
        log.info("dashboard.stop", port=port)

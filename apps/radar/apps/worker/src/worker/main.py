"""APScheduler entrypoint — hourly RSS sync + opt-in auto-brief.

Phase 12-ii: brief generation manuel UI butonu olarak geri geldi.
Phase 20-ii: otomatik brief üretimi opt-in (RASATHANE_AUTO_BRIEF=1
env). Hourly cron round sonunda günün brief'i yoksa otomatik üretir;
mevcutsa skip (idempotent — already_exists guard Phase 12-ii'den).
"""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from llm.translate import translate_short_pending
from store.database import session_factory

from worker.sync import sync_all_enabled

log = structlog.get_logger()

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _auto_brief_enabled() -> bool:
    """Phase 20-ii: opt-in env. Default off (manuel UI butonu canonical)."""
    return os.environ.get("RASATHANE_AUTO_BRIEF", "").strip().lower() in _TRUTHY


async def _hourly_sync_job() -> None:
    """One ingestion round across all enabled sources, then translate new ones,
    then (optionally) auto-generate today's brief if missing.
    """
    log.info("hourly_sync.starting")
    async with session_factory() as session:
        results = await sync_all_enabled(session)
    log.info("hourly_sync.done", results=results)

    # Post-sync translation: yeni eklenen + birikmiş NULL'lar.
    # session yeni açılır çünkü sync_all_enabled içinde commit edilmiş;
    # pipeline kendi commit'lerini yönetir.
    try:
        async with session_factory() as session:
            success, fail = await translate_short_pending(session, limit=100)
        log.info("hourly_sync.translate_done", success=success, fail=fail)
    except Exception as e:
        # translation başarısızlığı sync sonuçlarını invalide etmez
        log.error("hourly_sync.translate_failed", err=str(e)[:200])

    # Phase 20-ii: otomatik brief üretimi (opt-in)
    if _auto_brief_enabled():
        try:
            from rasathane_mcp.core.brief import generate_brief
            from rasathane_mcp.core.paths import ARCHIVE_ROOT

            async with session_factory() as session:
                result = await generate_brief(session, archive_root=ARCHIVE_ROOT, force=False)
            # generate_brief idempotent: bugünün brief'i varsa already_exists döner
            if result.get("error") == "already_exists":
                log.info("hourly_sync.auto_brief.skip_cached")
            elif result.get("error") == "in_progress":
                log.info("hourly_sync.auto_brief.skip_locked")
            elif result.get("error"):
                log.warning("hourly_sync.auto_brief.failed", err=result["error"])
            else:
                log.info(
                    "hourly_sync.auto_brief.done",
                    date=result.get("date"),
                    started_at=result.get("started_at"),
                )
        except Exception as e:
            log.error("hourly_sync.auto_brief.exception", err=str(e)[:200])


async def main() -> None:
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(
        _hourly_sync_job,
        trigger="interval",
        hours=1,
        id="rss_sync_hourly",
        coalesce=True,
        max_instances=1,
        next_run_time=None,
    )
    scheduler.start()
    log.info("worker.started", jobs=[j.id for j in scheduler.get_jobs()])

    stop_event = asyncio.Event()

    def _stop(*_: Any) -> None:
        log.info("worker.signal_received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, _stop)

    await stop_event.wait()
    scheduler.shutdown(wait=True)
    log.info("worker.stopped")


if __name__ == "__main__":
    asyncio.run(main())

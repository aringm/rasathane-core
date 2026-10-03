"""Single-source sync helper — used by the worker scheduler and the dashboard.

Both surfaces (background scheduler in ``worker.sync.sync_all_enabled`` and
the dashboard's manual-sync button) call this to fetch+upsert one feed.
Keeping the per-source step in ``ingestion`` lets the dashboard depend on
it without pulling APScheduler/Typer from the worker app.

Caller manages the transaction (no commit inside).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from store.models import Source
from store.repository import upsert_articles

from ingestion.registry import get_ingester

log = structlog.get_logger()


async def sync_one_source(session: AsyncSession, source: Source) -> int:
    """Fetch articles from one source and upsert into DB.

    Returns the number of newly-inserted articles. Updates
    ``source.last_fetched_at``. Caller manages the transaction.
    """
    ingester = get_ingester(source.type)
    articles = await ingester.fetch(source.url, metadata=source.metadata_)
    rows = [a.model_dump() for a in articles]
    inserted = await upsert_articles(session, source.id, rows)
    source.last_fetched_at = datetime.now(UTC)
    return inserted

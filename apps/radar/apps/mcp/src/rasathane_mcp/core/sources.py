"""Source-listing query, shared between the MCP tool and the dashboard."""

from __future__ import annotations

from sqlalchemy import select
from store.database import session_factory
from store.models import Source


async def list_sources(
    *,
    category: str | None = None,
    type_: str | None = None,
    enabled_only: bool = True,
) -> list[Source]:
    """Return Source rows filtered + ordered as both UI surfaces expect."""
    async with session_factory() as session:
        stmt = select(Source)
        if enabled_only:
            # Effective enabled: feeds.yaml flag AND no dashboard override.
            stmt = stmt.where(Source.enabled.is_(True), Source.is_user_disabled.is_(False))
        if category:
            stmt = stmt.where(Source.category == category)
        if type_:
            stmt = stmt.where(Source.type == type_)
        stmt = stmt.order_by(Source.category, Source.name)
        result = await session.execute(stmt)
        return list(result.scalars().all())

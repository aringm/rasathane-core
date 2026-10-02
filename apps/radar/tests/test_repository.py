"""Repository integration tests — require live PostgreSQL with pgvector.

Run via:  uv run pytest tests/test_repository.py
Spin up DB:  docker compose up -d postgres
Apply schema: uv run --package rasathane-store \\
                 alembic -c packages/store/alembic.ini upgrade head
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from store.models import Article, Source
from store.repository import (
    find_pending_short,
    list_enabled_sources,
    set_summary_tr_short,
    set_user_disabled,
    upsert_articles,
    upsert_sources_from_dicts,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://rasathane:rasathane@localhost:5435/rasathane",
)

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        try:
            yield s
        finally:
            await s.rollback()  # never persist test data
    await engine.dispose()


async def test_upsert_articles_dedupes_by_url_hash(session: AsyncSession) -> None:
    src = Source(
        name=f"Test source {uuid.uuid4().hex[:8]}",
        category="dunya_ai",
        type="rss",
        url=f"https://example.com/{uuid.uuid4().hex[:8]}/feed.xml",
    )
    session.add(src)
    await session.flush()

    article = {
        "url": f"https://example.com/{uuid.uuid4().hex[:8]}/article",
        "url_hash": (uuid.uuid4().hex + uuid.uuid4().hex)[:64],  # unique 64-char hex
        "title": "Test article",
        "metadata": {},
    }

    inserted_first = await upsert_articles(session, src.id, [article, article])
    assert inserted_first == 1, "duplicate within same call should dedupe"

    inserted_second = await upsert_articles(session, src.id, [article])
    assert inserted_second == 0, "already in DB should be skipped"


async def test_upsert_sources_idempotent(session: AsyncSession) -> None:
    name = f"Idemp {uuid.uuid4().hex[:8]}"
    url = f"https://example.com/{uuid.uuid4().hex[:8]}/feed.xml"
    yaml_data = [
        {
            "name": name,
            "category": "turk_hukuku",
            "type": "rss",
            "url": url,
            "enabled": True,
            "fetch_interval_minutes": 90,
            "metadata": {"lang": "tr"},
        }
    ]

    inserted_1, updated_1 = await upsert_sources_from_dicts(session, yaml_data)
    assert (inserted_1, updated_1) == (1, 0)

    yaml_data[0]["fetch_interval_minutes"] = 30
    inserted_2, updated_2 = await upsert_sources_from_dicts(session, yaml_data)
    assert (inserted_2, updated_2) == (0, 1)


async def test_set_user_disabled_toggles_and_returns_state(session: AsyncSession) -> None:
    src = Source(
        name=f"Toggle {uuid.uuid4().hex[:8]}",
        category="dunya_ai",
        type="rss",
        url=f"https://example.com/{uuid.uuid4().hex[:8]}/feed.xml",
        enabled=True,
    )
    session.add(src)
    await session.flush()

    # Mute via dashboard.
    effective = await set_user_disabled(session, src.id, disabled=True)
    assert effective is False
    await session.flush()
    assert src.is_user_disabled is True

    # Un-mute.
    effective = await set_user_disabled(session, src.id, disabled=False)
    assert effective is True
    await session.flush()
    assert src.is_user_disabled is False


async def test_set_user_disabled_raises_for_unknown_source(session: AsyncSession) -> None:
    with pytest.raises(LookupError):
        await set_user_disabled(session, uuid.uuid4(), disabled=True)


async def test_list_enabled_sources_excludes_user_disabled(session: AsyncSession) -> None:
    """User-disabled rows should disappear from the worker fetch list."""
    suffix = uuid.uuid4().hex[:8]
    a = Source(
        name=f"On {suffix}",
        category="dunya_ai",
        type="rss",
        url=f"https://example.com/a-{suffix}.xml",
        enabled=True,
    )
    b = Source(
        name=f"User-muted {suffix}",
        category="dunya_ai",
        type="rss",
        url=f"https://example.com/b-{suffix}.xml",
        enabled=True,
        is_user_disabled=True,
    )
    c = Source(
        name=f"Feeds-disabled {suffix}",
        category="dunya_ai",
        type="rss",
        url=f"https://example.com/c-{suffix}.xml",
        enabled=False,
    )
    session.add_all([a, b, c])
    await session.flush()

    rows = await list_enabled_sources(session)
    names = {s.name for s in rows}
    assert a.name in names
    assert b.name not in names  # user-disabled hidden
    assert c.name not in names  # feeds-disabled hidden


# --- Phase 12-i.3: find_pending_short / set_summary_tr_short ---


async def _make_source(session: AsyncSession) -> Source:
    """Helper: create a fresh Source with unique name/url and flush it."""
    suffix = uuid.uuid4().hex[:8]
    src = Source(
        name=f"Pending {suffix}",
        category="dunya_ai",
        type="rss",
        url=f"https://example.com/{suffix}/feed.xml",
    )
    session.add(src)
    await session.flush()
    return src


async def _insert_articles(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    items: list[dict],
) -> list[Article]:
    """Helper: build Article rows directly (bypasses upsert dedupe quirks).

    Each item may set ``summary``, ``summary_tr_short``, ``fetched_at``;
    ``url_hash`` is auto-derived from a unique uuid so callers don't repeat themselves.
    """
    created: list[Article] = []
    for item in items:
        url_hash = (uuid.uuid4().hex + uuid.uuid4().hex)[:64]
        kwargs = {
            "source_id": source_id,
            "url": item["url"],
            "url_hash": url_hash,
            "title": item["title"],
            "summary": item.get("summary"),
            "summary_tr_short": item.get("summary_tr_short"),
        }
        if "fetched_at" in item:
            kwargs["fetched_at"] = item["fetched_at"]
        art = Article(**kwargs)
        session.add(art)
        created.append(art)
    await session.flush()
    return created


async def test_find_pending_short_returns_only_null(session: AsyncSession) -> None:
    """find_pending_short skips articles that already have summary_tr_short."""
    src = await _make_source(session)
    suffix = uuid.uuid4().hex[:8]
    arts = await _insert_articles(
        session,
        source_id=src.id,
        items=[
            {
                "url": f"https://e.com/{suffix}/1",
                "title": f"T1-{suffix}",
                "summary": "s1",
                "summary_tr_short": None,
            },
            {
                "url": f"https://e.com/{suffix}/2",
                "title": f"T2-{suffix}",
                "summary": "s2",
                "summary_tr_short": "Hazır özet",
            },
            {
                "url": f"https://e.com/{suffix}/3",
                "title": f"T3-{suffix}",
                "summary": "s3",
                "summary_tr_short": None,
            },
        ],
    )

    pending = await find_pending_short(session, limit=10)

    pending_ids = {a.id for a in pending}
    assert arts[0].id in pending_ids
    assert arts[1].id not in pending_ids  # already has summary_tr_short
    assert arts[2].id in pending_ids


async def test_find_pending_short_orders_by_fetched_at_desc(session: AsyncSession) -> None:
    """find_pending_short returns most recent first."""
    src = await _make_source(session)
    suffix = uuid.uuid4().hex[:8]
    now = datetime.now(UTC)
    arts = await _insert_articles(
        session,
        source_id=src.id,
        items=[
            {
                "url": f"https://e.com/{suffix}/old",
                "title": f"old-{suffix}",
                "summary": None,
                "summary_tr_short": None,
                "fetched_at": now - timedelta(hours=5),
            },
            {
                "url": f"https://e.com/{suffix}/new",
                "title": f"new-{suffix}",
                "summary": None,
                "summary_tr_short": None,
                "fetched_at": now - timedelta(minutes=5),
            },
        ],
    )

    # Limit yüksek tut: 4000+ makaleli prod DB'de top 10 içine girmeyebiliriz.
    # Bizim 2 row'umuz son fetched, başa yakın olur ama tail'de eski NULL'lar
    # olabilir.
    pending = await find_pending_short(session, limit=10_000)

    # Filter to just our two test rows
    our_ids = {arts[0].id, arts[1].id}
    ordered = [a for a in pending if a.id in our_ids]
    assert [a.title for a in ordered] == [f"new-{suffix}", f"old-{suffix}"]


async def test_find_pending_short_respects_limit(session: AsyncSession) -> None:
    src = await _make_source(session)
    suffix = uuid.uuid4().hex[:8]
    await _insert_articles(
        session,
        source_id=src.id,
        items=[
            {
                "url": f"https://e.com/{suffix}/{i}",
                "title": f"T{i}-{suffix}",
                "summary": None,
                "summary_tr_short": None,
            }
            for i in range(5)
        ],
    )

    pending = await find_pending_short(session, limit=2)

    assert len(pending) == 2


async def test_set_summary_tr_short_writes_value(session: AsyncSession) -> None:
    src = await _make_source(session)
    suffix = uuid.uuid4().hex[:8]
    [art] = await _insert_articles(
        session,
        source_id=src.id,
        items=[
            {
                "url": f"https://e.com/{suffix}/x",
                "title": f"T-{suffix}",
                "summary": "s",
                "summary_tr_short": None,
            },
        ],
    )

    await set_summary_tr_short(session, art.id, "Bu Türkçe özet.")
    await session.flush()

    refreshed = await session.get(Article, art.id)
    assert refreshed is not None
    assert refreshed.summary_tr_short == "Bu Türkçe özet."


async def test_set_summary_tr_short_unknown_id_raises(session: AsyncSession) -> None:
    with pytest.raises(LookupError, match=r"article .* not found"):
        await set_summary_tr_short(session, uuid.uuid4(), "x")

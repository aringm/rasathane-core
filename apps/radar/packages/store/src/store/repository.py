"""High-level repository helpers on top of SQLAlchemy models.

These centralize dedup logic so ingesters and analysers never write SQL
themselves.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import date as date_type
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from store.models import Article, LibraryItem, Source

EmbedFn = Callable[[Sequence[str]], Awaitable[list[list[float]]]]

log = structlog.get_logger()


async def upsert_articles(
    session: AsyncSession,
    source_id: uuid.UUID,
    articles: Sequence[dict[str, Any]],
) -> int:
    """Bulk INSERT articles with ON CONFLICT (url_hash) DO NOTHING.

    Returns the number of newly-inserted rows (i.e. dedupe-survivors).
    Each article dict MUST include ``url_hash``; ``source_id`` is set here
    so callers can pass DTOs without coupling them to FK ids.

    Caller is responsible for the transaction (no commit inside).
    """
    if not articles:
        return 0

    rows = [{**a, "source_id": source_id} for a in articles]
    # Use Core insert (Article.__table__) so DB column names map directly,
    # bypassing the ORM attribute → column rename (metadata_ → "metadata").
    stmt = (
        pg_insert(Article.__table__)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["url_hash"])
        .returning(Article.__table__.c.id)
    )
    result = await session.execute(stmt)
    inserted = len(result.scalars().all())
    skipped = len(rows) - inserted
    log.info(
        "upsert_articles",
        source_id=str(source_id),
        inserted=inserted,
        skipped_dupe=skipped,
    )
    return inserted


async def upsert_sources_from_dicts(
    session: AsyncSession,
    sources: Sequence[dict[str, Any]],
) -> tuple[int, int]:
    """Upsert ``Source`` rows (typically from feeds.yaml).

    Match key is the (name, type, url) tuple. If found, update
    ``enabled``, ``category``, ``fetch_interval_minutes`` and ``metadata``;
    otherwise insert a new row.

    Returns ``(inserted, updated)``. Caller commits.
    """
    inserted = 0
    updated = 0
    for s in sources:
        existing = (
            await session.execute(
                select(Source).where(
                    Source.name == s["name"],
                    Source.type == s["type"],
                    Source.url == s["url"],
                )
            )
        ).scalar_one_or_none()

        if existing:
            existing.enabled = s.get("enabled", True)
            existing.category = s["category"]
            existing.fetch_interval_minutes = s.get("fetch_interval_minutes", 60)
            existing.metadata_ = s.get("metadata", {})
            updated += 1
        else:
            session.add(
                Source(
                    name=s["name"],
                    category=s["category"],
                    type=s["type"],
                    url=s["url"],
                    enabled=s.get("enabled", True),
                    fetch_interval_minutes=s.get("fetch_interval_minutes", 60),
                    metadata_=s.get("metadata", {}),
                )
            )
            inserted += 1

    log.info(
        "upsert_sources",
        inserted=inserted,
        updated=updated,
        total=len(sources),
    )
    return inserted, updated


async def list_enabled_sources(session: AsyncSession) -> Sequence[Source]:
    """Return all *effectively* enabled ``Source`` rows ordered by category, name.

    Effective = ``enabled`` (feeds.yaml) AND NOT ``is_user_disabled`` (dashboard
    override). Workers, MCP tools, and the dashboard all share this filter so
    a single toggle in any surface mutes the source everywhere.
    """
    result = await session.execute(
        select(Source)
        .where(Source.enabled.is_(True), Source.is_user_disabled.is_(False))
        .order_by(Source.category, Source.name)
    )
    return result.scalars().all()


async def set_user_disabled(session: AsyncSession, source_id: uuid.UUID, *, disabled: bool) -> bool:
    """Toggle the dashboard-side ``is_user_disabled`` flag for one source.

    Returns the new effective-enabled state (``enabled AND NOT is_user_disabled``)
    so the caller can render the resulting UI without a follow-up SELECT.
    Raises ``LookupError`` if the source does not exist. Caller commits.
    """
    src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if src is None:
        raise LookupError(f"source {source_id} not found")
    src.is_user_disabled = disabled
    return src.enabled and not disabled


# ── Phase 15-iv: user-added sources (UI'dan ekle/sil) ──────────────────


class DuplicateSourceError(Exception):
    """Raised by add_user_source when a (name, type, url) already exists."""


class NotUserAddedError(Exception):
    """Raised by delete_user_source when target is yaml-managed."""


async def add_user_source(
    session: AsyncSession,
    *,
    name: str,
    category: str,
    type: str,  # noqa: A002 (matches Source field)
    url: str,
    fetch_interval_minutes: int = 60,
    extra_metadata: dict[str, Any] | None = None,
) -> Source:
    """Insert a Source flagged as user-added in metadata.

    feeds_yaml.sync_feeds_yaml_to_db won't touch this row because the
    upsert match is (name, type, url) — yaml has no entry, no match.
    Raises ``DuplicateSourceError`` if (name, type, url) collides.
    Caller commits.
    """
    existing = (
        await session.execute(
            select(Source).where(
                Source.name == name,
                Source.type == type,
                Source.url == url,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateSourceError(f"source already exists: {name!r} ({type}, {url})")

    metadata = dict(extra_metadata or {})
    metadata["added_by"] = "user"

    src = Source(
        name=name,
        category=category,
        type=type,
        url=url,
        enabled=True,
        fetch_interval_minutes=fetch_interval_minutes,
        metadata_=metadata,
    )
    session.add(src)
    await session.flush()
    log.info("source.user_added", name=name, category=category, type=type)
    return src


async def delete_user_source(session: AsyncSession, source_id: uuid.UUID) -> None:
    """Delete a Source row only if metadata.added_by == "user".

    Raises ``LookupError`` if not found, ``NotUserAddedError`` if
    yaml-managed (caller must use toggle instead). Caller commits.

    Note: associated Article rows have ON DELETE CASCADE in the schema,
    so deleting a user source also deletes all its articles. This is
    desired since user-added sources are "experimental" — keeping
    orphan articles after the source is removed would clutter the feed.
    """
    src = (await session.execute(select(Source).where(Source.id == source_id))).scalar_one_or_none()
    if src is None:
        raise LookupError(f"source {source_id} not found")
    if (src.metadata_ or {}).get("added_by") != "user":
        raise NotUserAddedError(f"source {source_id} is yaml-managed; edit data/feeds.yaml instead")
    await session.delete(src)
    log.info("source.user_deleted", source_id=str(source_id), name=src.name)


async def list_articles_since(
    session: AsyncSession,
    *,
    since: datetime,
    category: str | None = None,
    limit: int = 1000,
) -> Sequence[Article]:
    """Return articles ``fetched_at >= since`` (optionally filtered by category).

    Source is eager-loaded for template rendering. Sorted by ``published_at``
    DESC (NULLs last), then ``fetched_at`` DESC.
    """
    stmt = (
        select(Article)
        .options(selectinload(Article.source))
        .where(Article.fetched_at >= since)
        .order_by(Article.published_at.desc().nulls_last(), Article.fetched_at.desc())
        .limit(limit)
    )
    if category:
        stmt = stmt.join(Article.source).where(Source.category == category)

    result = await session.execute(stmt)
    return result.scalars().all()


async def embed_pending_articles(
    session: AsyncSession,
    *,
    embed_fn: EmbedFn,
    since: datetime | None = None,
    batch_size: int = 32,
    max_articles: int = 2000,
) -> int:
    """Fill in ``Article.embedding`` for rows where it's NULL.

    Picks up pending articles (optionally restricted to ``fetched_at >= since``),
    feeds title+summary text to ``embed_fn`` in batches, writes back the
    vectors. Returns count of newly-embedded rows. Caller commits.

    ``embed_fn`` signature: ``async (texts) -> list[list[float]]`` — typically
    ``llm.embeddings.embed_batch``.
    """
    stmt = select(Article).where(Article.embedding.is_(None))
    if since:
        stmt = stmt.where(Article.fetched_at >= since)
    stmt = stmt.order_by(Article.fetched_at.asc()).limit(max_articles)
    pending = list((await session.execute(stmt)).scalars().all())

    if not pending:
        log.info("embed_pending.nothing_to_do")
        return 0

    total = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        texts = [(a.title + ". " + (a.summary or "")).strip() or a.title for a in batch]
        vectors = await embed_fn(texts)
        for article, vec in zip(batch, vectors, strict=True):
            article.embedding = vec
        total += len(batch)
        log.info(
            "embed_pending.batch",
            batch_index=i // batch_size + 1,
            done=total,
            total=len(pending),
        )

    return total


async def find_pending_short(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> Sequence[Article]:
    """En yeni N makaleyi döndür ki ``summary_tr_short`` IS NULL.

    Hourly cron + ``pulse translate-pending`` aynı sorguyu kullanır
    (DRY). ``fetched_at DESC`` sıralı; tail'deki eski NULL'lar batch
    sınırı içinde kalmazsa bir sonraki çağrıda gelir.
    """
    stmt = (
        select(Article)
        .where(Article.summary_tr_short.is_(None))
        .order_by(Article.fetched_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def set_summary_tr_short(
    session: AsyncSession,
    article_id: uuid.UUID,
    text: str,
) -> None:
    """``Article.summary_tr_short`` kolonunu güncelle.

    Bilinmeyen id için ``LookupError`` fırlatır. Caller commit eder
    (batch update'in atomik olması için).
    """
    art = (
        await session.execute(select(Article).where(Article.id == article_id))
    ).scalar_one_or_none()
    if art is None:
        raise LookupError(f"article {article_id} not found")
    art.summary_tr_short = text


# ── Phase 32-ii: TR başlık çevirisi (metadata JSON kolonu) ───────────


async def find_pending_title_tr(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> Sequence[Article]:
    """Türkçe başlık çevirisi bekleyen makaleleri döndür.

    Heuristic: ``Source.metadata.lang != 'tr'`` ve henüz ``metadata.title_tr``
    yok. JSON path filter Python tarafında — JSON kolon (JSONB değil)
    olduğu için SQL-side ``?`` operatörü güvenilmez. Bir batch limit ×
    1.5 makale çekilir, Python'da filtrelenir, ilk N döndürülür.

    ``fetched_at DESC`` sıralı (yeni makaleler önce — kullanıcı en çok
    onları görür).
    """
    # Limit'i artırıyoruz ki Python filter sonrası yeterli kalsın
    raw_limit = max(limit * 2, 50)
    stmt = (
        select(Article)
        .options(selectinload(Article.source))
        .order_by(Article.fetched_at.desc())
        .limit(raw_limit)
    )
    result = await session.execute(stmt)
    rows = result.scalars().all()
    out: list[Article] = []
    for art in rows:
        source_lang = (art.source.metadata_ or {}).get("lang", "").lower()
        # Sadece İngilizce ve diğer Latin alfabesi kaynaklar — Türkçe
        # kaynaklarda zaten TR başlık var, ek çeviri gereksiz.
        if source_lang == "tr":
            continue
        # title_tr metadata'da yoksa pending
        if (art.metadata_ or {}).get("title_tr"):
            continue
        out.append(art)
        if len(out) >= limit:
            break
    return out


async def set_article_title_tr(
    session: AsyncSession,
    article_id: uuid.UUID,
    title_tr: str,
) -> None:
    """``Article.metadata.title_tr`` JSON kolonuna TR başlığı yaz.

    Mutable JSON: SQLAlchemy değişikliği otomatik fark etmez —
    ``flag_modified`` zorunlu. Bilinmeyen id için ``LookupError``.
    Caller commit eder.
    """
    from sqlalchemy.orm.attributes import flag_modified

    art = (
        await session.execute(select(Article).where(Article.id == article_id))
    ).scalar_one_or_none()
    if art is None:
        raise LookupError(f"article {article_id} not found")
    meta = dict(art.metadata_ or {})
    meta["title_tr"] = title_tr
    art.metadata_ = meta
    flag_modified(art, "metadata_")


# ─── Phase 12-iii: Kütüphane (LibraryItem) ──────────────────────────────


class AlreadySavedError(Exception):
    """Kütüphaneye eklenmek istenen item zaten var (idempotent guard)."""


async def save_article_to_library(
    session: AsyncSession,
    *,
    article_id: uuid.UUID,
    note: str | None,
    snapshot_md: str,
    snapshot_meta: dict[str, Any],
) -> LibraryItem:
    """Bir makaleyi kütüphaneye kaydet (idempotent guard ile)."""
    existing = (
        await session.execute(select(LibraryItem).where(LibraryItem.article_id == article_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise AlreadySavedError(str(existing.id))
    item = LibraryItem(
        item_type="article",
        article_id=article_id,
        note=note,
        snapshot_md=snapshot_md,
        snapshot_meta=snapshot_meta,
    )
    session.add(item)
    await session.flush()
    return item


async def save_brief_to_library(
    session: AsyncSession,
    *,
    brief_date: date_type,
    note: str | None,
    snapshot_md: str,
    snapshot_meta: dict[str, Any],
) -> LibraryItem:
    """Bir günün brief'ini kütüphaneye kaydet."""
    existing = (
        await session.execute(select(LibraryItem).where(LibraryItem.brief_date == brief_date))
    ).scalar_one_or_none()
    if existing is not None:
        raise AlreadySavedError(str(existing.id))
    item = LibraryItem(
        item_type="brief",
        brief_date=brief_date,
        note=note,
        snapshot_md=snapshot_md,
        snapshot_meta=snapshot_meta,
    )
    session.add(item)
    await session.flush()
    return item


async def save_deep_analysis_to_library(
    session: AsyncSession,
    *,
    job_id: str,
    note: str | None,
    snapshot_md: str,
    snapshot_meta: dict[str, Any],
) -> LibraryItem:
    """Phase 17-v: bir deep-analyze job'unu kütüphaneye kaydet.

    snapshot_md = compose(transcript, summary) — Türkçe okuma için
    birleşik markdown. mindmap.html + audio.mp3 dosyaları snapshot
    olarak DB'ye kopyalanmaz; snapshot_meta path'leri tutar
    (kütüphane silinene kadar archive/deep/ içinde kalır).
    """
    existing = (
        await session.execute(select(LibraryItem).where(LibraryItem.deep_analysis_job_id == job_id))
    ).scalar_one_or_none()
    if existing is not None:
        raise AlreadySavedError(str(existing.id))
    item = LibraryItem(
        item_type="deep_analysis",
        deep_analysis_job_id=job_id,
        note=note,
        snapshot_md=snapshot_md,
        snapshot_meta=snapshot_meta,
    )
    session.add(item)
    await session.flush()
    return item


async def list_library_items(
    session: AsyncSession,
    *,
    item_type: str | None = None,
    q: str | None = None,
    offset: int = 0,
    limit: int = 50,
) -> tuple[Sequence[LibraryItem], int]:
    """Kütüphane listesi; ``saved_at DESC`` sıralı.

    item_type filter: ``"article"`` | ``"brief"`` | None (hepsi).
    q filter: note + snapshot_meta.title + snapshot_md ILIKE araması.
    Returns (items, total_count).
    """
    base = select(LibraryItem)
    if item_type in ("article", "brief"):
        base = base.where(LibraryItem.item_type == item_type)
    if q:
        pat = f"%{q}%"
        # JSONB'den title çekmek için ->> operator
        base = base.where(
            or_(
                LibraryItem.note.ilike(pat),
                LibraryItem.snapshot_md.ilike(pat),
                LibraryItem.snapshot_meta["title"].astext.ilike(pat),
            )
        )

    # Total count (filter dahil)
    from sqlalchemy import func as sa_func

    count_stmt = select(sa_func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    items_stmt = (
        base.options(selectinload(LibraryItem.article).selectinload(Article.source))
        .order_by(LibraryItem.saved_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(items_stmt)).scalars().all()
    return rows, int(total)


async def get_library_item(session: AsyncSession, item_id: uuid.UUID) -> LibraryItem | None:
    return (
        await session.execute(
            select(LibraryItem)
            .options(selectinload(LibraryItem.article).selectinload(Article.source))
            .where(LibraryItem.id == item_id)
        )
    ).scalar_one_or_none()


async def delete_library_item(session: AsyncSession, item_id: uuid.UUID) -> bool:
    item = await get_library_item(session, item_id)
    if item is None:
        return False
    await session.delete(item)
    return True


async def update_library_note(
    session: AsyncSession, item_id: uuid.UUID, note: str | None
) -> LibraryItem | None:
    item = await get_library_item(session, item_id)
    if item is None:
        return None
    item.note = note
    return item

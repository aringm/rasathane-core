"""Pulse CLI — ingestion + DB maintenance commands.

Phase 10-i pivot ("the great cleanup"): everything that depended on
``ANTHROPIC_API_KEY`` is gone. The interactive flow lives in Claude
Desktop via the Rasathane MCP server (``apps/mcp``). What remains here
is the autonomous data layer: source catalogue sync, hourly RSS pull,
and Ollama-backed embedding refill.

Phase 10-ii will reintroduce a ``daily-brief`` command via ``claude``
CLI subprocess (subscription, no key) — but for now we keep the surface
small and honest.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import structlog
import typer
from ingestion.feeds_yaml import sync_feeds_yaml_to_db
from llm.embeddings import embed_batch
from llm.translate import translate_short_pending
from store.database import session_factory
from store.repository import embed_pending_articles, list_enabled_sources

from worker.sync import sync_all_enabled

app = typer.Typer(
    help="Rasathane CLI — pulse",
    no_args_is_help=True,
    add_completion=False,
)
log = structlog.get_logger()

DEFAULT_FEEDS_PATH = Path("data/feeds.yaml")


@app.command()
def sync(
    feeds_yaml: Annotated[
        Path,
        typer.Option(
            "--feeds-yaml",
            "-f",
            help="Auto-upsert sources from this yaml first; pass empty path to skip.",
        ),
    ] = DEFAULT_FEEDS_PATH,
) -> None:
    """Run a single fetch round across all enabled sources."""
    # Resolve filesystem state in the sync layer so the async path stays
    # filesystem-free (ASYNC240 — no blocking syscalls in async fns).
    resolved = feeds_yaml if feeds_yaml.exists() else None
    asyncio.run(_sync_cmd(resolved))


async def _sync_cmd(feeds_yaml: Path | None) -> None:
    async with session_factory() as session:
        if feeds_yaml is not None:
            inserted, updated = await sync_feeds_yaml_to_db(session, feeds_yaml)
            await session.commit()
            typer.echo(f"sources: +{inserted} new, ~{updated} updated")
        results = await sync_all_enabled(session)
        ok = sum(1 for v in results.values() if v >= 0)
        failed = sum(1 for v in results.values() if v < 0)
        new = sum(v for v in results.values() if v > 0)
        typer.echo(
            f"OK: {ok}/{len(results)} sources fetched, +{new} new articles ({failed} failed)"
        )


@app.command(name="sync-feeds")
def sync_feeds(
    feeds_yaml: Annotated[
        Path,
        typer.Argument(help="Path to feeds.yaml"),
    ] = DEFAULT_FEEDS_PATH,
) -> None:
    """Upsert ``Source`` rows from feeds.yaml (no fetch)."""
    asyncio.run(_sync_feeds_cmd(feeds_yaml))


async def _sync_feeds_cmd(feeds_yaml: Path) -> None:
    async with session_factory() as session:
        inserted, updated = await sync_feeds_yaml_to_db(session, feeds_yaml)
        await session.commit()
        typer.echo(f"+{inserted} new sources, ~{updated} updated")


@app.command(name="list-sources")
def list_sources_cmd() -> None:
    """List all enabled ``Source`` rows."""
    asyncio.run(_list_sources_cmd())


async def _list_sources_cmd() -> None:
    async with session_factory() as session:
        sources = await list_enabled_sources(session)
        if not sources:
            typer.echo("No enabled sources. Run `pulse sync-feeds` first.")
            return
        for s in sources:
            last = s.last_fetched_at.isoformat() if s.last_fetched_at else "never"
            typer.echo(f"  [{s.category:18}] {s.type:6} {s.name}  ({last})")


@app.command()
def embed(
    since_hours: Annotated[
        int,
        typer.Option(
            "--since-hours",
            "-s",
            help="Embed articles fetched in the last N hours.",
        ),
    ] = 24,
    max_articles: Annotated[
        int,
        typer.Option(
            "--max",
            help="Cap on articles to embed in one run (safety).",
        ),
    ] = 2000,
) -> None:
    """Fill in NULL embeddings for recent articles via Ollama (used by MCP search_articles)."""
    asyncio.run(_embed_cmd(since_hours, max_articles))


async def _embed_cmd(since_hours: int, max_articles: int) -> None:
    since = datetime.now(UTC) - timedelta(hours=since_hours)
    async with session_factory() as session:
        n = await embed_pending_articles(
            session,
            embed_fn=embed_batch,
            since=since,
            max_articles=max_articles,
        )
        if n:
            await session.commit()
        typer.echo(f"embedded {n} article(s)")


@app.command(name="translate-pending")
def translate_pending_cmd(
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-l",
            help="Tek seferde işlenecek makale sayısı (en yeni NULL'lar).",
        ),
    ] = 100,
) -> None:
    """summary_tr_short NULL olan en yeni makaleler için Türkçe özet üret.

    Idempotent — başarısız olanlar NULL kalır, bir sonraki çağrıda tekrar
    denenir. Hourly cron'la aynı kod yolunu paylaşır (DRY).
    """
    asyncio.run(_translate_pending_cmd(limit))


async def _translate_pending_cmd(limit: int) -> None:
    async with session_factory() as session:
        success, fail = await translate_short_pending(session, limit=limit)
        typer.echo(f"translate-short: SUCCESS={success}, FAIL={fail}")


@app.command(name="probe-disabled")
def probe_disabled_cmd() -> None:
    """feeds.yaml'da `enabled: false` olan kaynakları HTTP probe et.

    Phase 16-iii: 2026-05-07 audit'i 18/18 kaynağın gerçekten ölü
    olduğunu doğruladı. Bu komut periyodik probe için: HTTP 200 + RSS
    XML body olanları (yaml notunu güncellemek için elle) raporlar.
    """
    asyncio.run(_probe_disabled_cmd())


async def _probe_disabled_cmd() -> None:
    """Disable yaml satırlarını paralel probe et + LIVE/DEAD raporu yaz."""
    import httpx
    import yaml as _yaml

    feeds_path = DEFAULT_FEEDS_PATH
    raw = _yaml.safe_load(feeds_path.read_text(encoding="utf-8"))
    disabled = [s for s in raw["sources"] if s.get("enabled", True) is False]

    async def probe(entry: dict) -> tuple[str, str, str]:
        url = entry["url"]
        name = entry["name"]
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
                r = await c.get(url, headers={"User-Agent": "rasathane-probe/1.0"})
                if r.status_code != 200:
                    return name, url, f"STATUS_{r.status_code}"
                body = r.text[:300]
                if "<?xml" in body or "<rss" in body or "<feed" in body:
                    return name, url, "LIVE"
                return name, url, "NOT_XML"
        except Exception as e:
            return name, url, f"ERR_{type(e).__name__}"

    results = await asyncio.gather(*[probe(e) for e in disabled])
    live = [r for r in results if r[2] == "LIVE"]
    dead = [r for r in results if r[2] != "LIVE"]
    typer.echo(f"probed {len(results)} disabled source(s)")
    typer.echo(f"  LIVE: {len(live)}")
    for name, _, _ in live:
        typer.echo(f"    + {name} (consider re-enabling)")
    typer.echo(f"  DEAD: {len(dead)}")
    for name, _, status in dead:
        typer.echo(f"    - {name}: {status}")


if __name__ == "__main__":
    app()

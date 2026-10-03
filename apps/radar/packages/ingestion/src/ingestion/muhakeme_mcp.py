"""muhakeme.ai MCP client — emsal arama for Phase 7 legal research.

Two transport modes (env-driven; SSE wins if both set):

    MUHAKEME_MCP_URL=https://...   →  SSE transport (production)
    MUHAKEME_MCP_COMMAND=node /path/to/server.js  →  stdio transport (local)

If neither is set, raises ``MuhakemeNotConfiguredError`` — caller (legal subflow,
brief injection, /legal/research endpoint) decides whether that's a hard
fail (HTTP 503) or graceful degrade (continue without emsals).

Tool surface used (all expose Pydantic-ish dicts):
    emsal_unified_ara(arananKelime, ...)  →  unified search across Yargıtay /
                                              AYM / Danıştay / KVKK / Rekabet /
                                              Sayıştay
    emsal_karar_getir(karar_id)            →  full text of a specific decision
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()


class MuhakemeNotConfiguredError(RuntimeError):
    """Raised when neither MUHAKEME_MCP_URL nor MUHAKEME_MCP_COMMAND is set."""


@dataclass(frozen=True)
class EmsalHit:
    """One emsal result from unified search (court-agnostic)."""

    court: str  # "yargitay" | "aym" | "danistay" | ...
    case_id: str  # e.g. "2024/123 E. 2024/456 K."
    title: str
    excerpt: str  # short excerpt or summary
    url: str | None
    raw: dict[str, Any]  # full raw payload, for cite/replay


@asynccontextmanager
async def _open_session():
    """Open an MCP ``ClientSession`` over the configured transport.

    Imports are local so the module can be imported without ``mcp`` package
    pre-installed (tests with mocks, etc.).
    """
    url = os.environ.get("MUHAKEME_MCP_URL", "").strip()
    command = os.environ.get("MUHAKEME_MCP_COMMAND", "").strip()

    if not url and not command:
        raise MuhakemeNotConfiguredError(
            "Neither MUHAKEME_MCP_URL (SSE) nor MUHAKEME_MCP_COMMAND (stdio) "
            "is set. Configure one of them in .env to enable legal research."
        )

    from mcp import ClientSession

    if url:
        from mcp.client.sse import sse_client

        async with sse_client(url) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            yield session
    else:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        # COMMAND is a shell-style string; split into executable + args.
        # Caller is responsible for providing safe values (env vars).
        parts = command.split()
        params = StdioServerParameters(command=parts[0], args=parts[1:] or [])
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            yield session


def _parse_emsal_payload(raw: dict[str, Any], default_court: str = "unknown") -> EmsalHit:
    """Best-effort EmsalHit extraction. muhakeme tool schemas may vary;
    we capture the raw payload too so callers can always cite the original."""
    court = raw.get("mahkeme") or raw.get("court") or raw.get("kaynak") or default_court
    case_id = raw.get("kararNo") or raw.get("case_id") or raw.get("esasNo") or raw.get("id", "")
    title = (
        raw.get("baslik") or raw.get("title") or raw.get("ozet") or raw.get("name", "(başlıksız)")
    )
    excerpt = raw.get("ozet") or raw.get("excerpt") or raw.get("kararMetni", "")[:500] or ""
    url = raw.get("url") or raw.get("link") or raw.get("kaynakUrl")
    return EmsalHit(
        court=str(court),
        case_id=str(case_id),
        title=str(title),
        excerpt=str(excerpt),
        url=str(url) if url else None,
        raw=raw,
    )


async def search_emsals(
    query: str,
    *,
    page_size: int = 10,
) -> list[EmsalHit]:
    """Run ``emsal_unified_ara`` against the configured MCP server.

    Returns a list of ``EmsalHit`` (may be empty if no matches). Raises
    ``MuhakemeNotConfiguredError`` if no transport is set; surface this to the
    user in /legal/research as 503.
    """
    if not query or not query.strip():
        raise ValueError("Cannot search emsals with empty query")

    async with _open_session() as session:
        result = await session.call_tool(
            "emsal_unified_ara",
            arguments={"arananKelime": query, "pageSize": page_size},
        )
        # MCP tool result has ``content`` (list of text/image blocks);
        # we only consume text. Real schema may also surface ``structured_content``.
        hits: list[EmsalHit] = []
        if hasattr(result, "structuredContent") and result.structuredContent:
            payload = result.structuredContent
            items = payload.get("results") if isinstance(payload, dict) else payload
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        hits.append(_parse_emsal_payload(item))
        elif hasattr(result, "content"):
            # Plain-text fallback: parse JSON blocks if any
            for block in result.content:
                text = getattr(block, "text", None)
                if not text:
                    continue
                import json

                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    items = payload.get("results", [payload])
                else:
                    items = payload if isinstance(payload, list) else []
                for item in items:
                    if isinstance(item, dict):
                        hits.append(_parse_emsal_payload(item))

        log.info(
            "muhakeme.search_emsals",
            query=query,
            hits=len(hits),
        )
        return hits


async def fetch_emsal_full(case_id: str, court: str) -> dict[str, Any]:
    """Get full text/metadata for one emsal — used for citation pages."""
    async with _open_session() as session:
        result = await session.call_tool(
            "emsal_karar_getir",
            arguments={"karar_id": case_id, "kaynak": court},
        )
        if hasattr(result, "structuredContent") and result.structuredContent:
            return dict(result.structuredContent)
        # Fallback to text content
        for block in getattr(result, "content", []):
            text = getattr(block, "text", None)
            if text:
                import json

                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return {"raw_text": text}
        return {}

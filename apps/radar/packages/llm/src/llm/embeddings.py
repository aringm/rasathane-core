"""Ollama-backed embeddings (1024-dim, multilingual including Türkçe).

Default model: ``qwen3-embedding:0.6b`` (already pulled, 1024-dim, fits
pgvector schema). Configurable via ``OLLAMA_MODEL_EMBED`` env var.
Swap to ``bge-m3`` later by setting that env to ``bge-m3`` and running
``ollama pull bge-m3``; ``embed_pending_articles`` will lazily refill.

We hit the Ollama HTTP endpoint directly via httpx — simpler dep surface
and avoids API drift between ollama-python versions.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Sequence

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger()

EMBEDDING_DIM = 1024  # must match store.models.EMBEDDING_DIM
HTTP_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


def _resolve_model() -> str:
    return os.environ.get("OLLAMA_MODEL_EMBED", "qwen3-embedding:0.6b")


def _resolve_host() -> str:
    """Return ``OLLAMA_HOST`` with an ``http://`` scheme if user omitted it.

    Resolved lazily at call time (not module load) so monkeypatch works
    in tests and runtime env changes take effect.

    Two Windows-specific gotchas are handled defensively:
      1. ``localhost`` is rewritten to ``127.0.0.1`` — Python asyncio
         resolvers prefer IPv6 (::1), but Ollama listens IPv4-only by
         default → ConnectError despite Ollama being up.
      2. ``0.0.0.0`` is rewritten to ``127.0.0.1`` — Ollama's own
         default ``OLLAMA_HOST=0.0.0.0:11434`` is a server-side bind
         address (listen everywhere), NOT a client-connect address.
         Linux silently fallbacks to 127.0.0.1; Windows refuses outright.
    """
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    url = raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
    return url.replace("://0.0.0.0:", "://127.0.0.1:").replace("://localhost:", "://127.0.0.1:")


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def embed_text(text: str, *, model: str | None = None) -> list[float]:
    """Embed a single text. Returns 1024-dim list[float]."""
    if not text or not text.strip():
        raise ValueError("Cannot embed empty text")

    payload = {"model": model or _resolve_model(), "prompt": text}
    async with httpx.AsyncClient(base_url=_resolve_host(), timeout=HTTP_TIMEOUT) as client:
        response = await client.post("/api/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()

    vec = data["embedding"]
    if len(vec) != EMBEDDING_DIM:
        raise RuntimeError(
            f"Embedding dim mismatch: expected {EMBEDDING_DIM}, got {len(vec)}. "
            f"Model {payload['model']!r} has wrong output dim for this schema."
        )
    return vec


async def embed_batch(
    texts: Sequence[str],
    *,
    model: str | None = None,
    concurrency: int = 4,
) -> list[list[float]]:
    """Embed multiple texts in parallel (concurrency-limited).

    Maintains input order in the output. Raises on first failure.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(t: str) -> list[float]:
        async with sem:
            return await embed_text(t, model=model)

    return await asyncio.gather(*[_one(t) for t in texts])

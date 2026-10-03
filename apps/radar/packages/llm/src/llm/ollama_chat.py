"""Hybrid local-LLM client (LM Studio kalite-tercihli + Ollama fallback).

Phase 29: Heavy-bootstrap ``claude.CMD`` subprocess'i 100K+ char prompt'larda
600sn timeout'u aşıyordu. Local LLM reasoning gerektirmeyen mekanik metin
görevlerinde drop-in replacement.

Phase 29-ii: A/B benchmark sonrası **kalite-öncelikli hibrit**:
LM Studio'daki ``google/gemma-4-26b-a4b`` (Q8 MoE, 4B aktif) Ollama'daki
varyantlardan kaliteli + benzer hızda — TR'ye doğal çeviri ("Hanımefendiler
ve beyefendiler"), prompt'un istediği `**term** (English)` parens-format
kuralına sadık. Ollama'daki gemma4 sürümleri sadece Dense Q4 (e2b/e4b/31b);
MoE Q8 versiyonu Ollama hub'ında yok, custom GGUF import'u Gemma 4 için
RENDERER+PARSER metadata gerektirdiği için fragile.

Karar: LM Studio (kalite, MoE+Q8) tercih edilir, Ollama (hız, hep hazır)
fallback. Ollama embeddings için zaten daemon olduğundan ek yük yok.

Provider seçimi (env):
  - ``LOCAL_LLM_PROVIDER=auto`` (default) — LM Studio dene, başarısızsa
    Ollama'ya düş
  - ``LOCAL_LLM_PROVIDER=lmstudio`` — sadece LM Studio (fail = error)
  - ``LOCAL_LLM_PROVIDER=ollama`` — sadece Ollama (LM Studio'yu hiç deneme)

Model seçimi (env):
  - ``LMSTUDIO_MODEL_CHAT`` — default ``google/gemma-4-26b-a4b``
  - ``OLLAMA_MODEL_CHAT`` — default ``qwen3:8b``

LM Studio auto-start:
  - Server down ise ``lms server start --port 1234`` (cold start ~0.6sn)
  - Model yüklü değilse ``lms load <model> --ttl 600 --yes`` (cold load ~40sn,
    sonra 10dk idle TTL)
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = structlog.get_logger()

# ── Defaults ──────────────────────────────────────────────────────────
_OLLAMA_DEFAULT_MODEL = "qwen3:8b"
_LMSTUDIO_DEFAULT_MODEL = "google/gemma-4-26b-a4b"
_LMSTUDIO_DEFAULT_PORT = 1234
_LMSTUDIO_MODEL_TTL_SECONDS = 600
# Local GPU 200K char input için 30-180sn tipik; 600sn yastık.
_DEFAULT_TIMEOUT_SECONDS = 600


class _LMStudioUnavailableError(RuntimeError):
    """LM Studio kullanılamıyor — auto provider Ollama'ya fallback edebilir."""


def _resolve_provider() -> str:
    raw = os.environ.get("LOCAL_LLM_PROVIDER", "auto").lower().strip()
    if raw not in ("auto", "lmstudio", "ollama"):
        log.warning("local_llm.unknown_provider", value=raw, falling_back="auto")
        return "auto"
    return raw


def _resolve_ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL_CHAT", _OLLAMA_DEFAULT_MODEL)


def _resolve_lmstudio_model() -> str:
    return os.environ.get("LMSTUDIO_MODEL_CHAT", _LMSTUDIO_DEFAULT_MODEL)


def _resolve_ollama_host() -> str:
    """Return ``OLLAMA_HOST`` with ``http://`` scheme prefix.

    Windows-specific gotchas (mirror of ``embeddings._resolve_host``):
      1. ``localhost`` → ``127.0.0.1`` (asyncio prefers IPv6 ``::1``,
         Ollama listens IPv4-only by default).
      2. ``0.0.0.0`` → ``127.0.0.1`` (server bind addr ≠ client connect addr;
         Linux fallbacks silently, Windows refuses).
    """
    raw = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    url = raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
    return url.replace("://0.0.0.0:", "://127.0.0.1:").replace("://localhost:", "://127.0.0.1:")


def _resolve_lmstudio_host() -> str:
    raw = os.environ.get("LMSTUDIO_HOST", f"http://127.0.0.1:{_LMSTUDIO_DEFAULT_PORT}")
    url = raw if raw.startswith(("http://", "https://")) else f"http://{raw}"
    return url.replace("://0.0.0.0:", "://127.0.0.1:").replace("://localhost:", "://127.0.0.1:")


# ── LM Studio path ────────────────────────────────────────────────────


async def _lmstudio_server_up(client: httpx.AsyncClient, host: str) -> bool:
    """Probe ``/v1/models`` — server up = response 200."""
    try:
        r = await client.get(f"{host}/v1/models", timeout=2)
        return r.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
        return False


def _lmstudio_start_server() -> None:
    """Spawn ``lms server start``. Sync — runs in thread via asyncio.to_thread.

    Raises ``_LMStudioUnavailableError`` if ``lms`` CLI yok ya da start başarısız.
    """
    cli = shutil.which("lms")
    if cli is None:
        raise _LMStudioUnavailableError("lms CLI not in PATH")
    try:
        proc = subprocess.run(
            [cli, "server", "start", "--port", str(_LMSTUDIO_DEFAULT_PORT)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise _LMStudioUnavailableError(f"lms server start timeout: {e}") from e
    if proc.returncode != 0:
        raise _LMStudioUnavailableError(
            f"lms server start rc={proc.returncode}: {proc.stderr or proc.stdout}"
        )


def _lmstudio_load_model(model: str) -> None:
    """``lms load <model> --ttl <s> --yes`` — idempotent (no-op if loaded)."""
    cli = shutil.which("lms")
    if cli is None:
        raise _LMStudioUnavailableError("lms CLI not in PATH")
    try:
        proc = subprocess.run(
            [cli, "load", model, "--ttl", str(_LMSTUDIO_MODEL_TTL_SECONDS), "--yes"],
            capture_output=True,
            text=True,
            timeout=180,  # cold load 40sn typical, 180sn safety
            check=False,
            shell=False,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise _LMStudioUnavailableError(f"lms load timeout for {model}: {e}") from e
    if proc.returncode != 0:
        raise _LMStudioUnavailableError(
            f"lms load {model} rc={proc.returncode}: {proc.stderr or proc.stdout}"
        )


async def _lmstudio_call(
    client: httpx.AsyncClient,
    *,
    host: str,
    model: str,
    prompt: str,
    timeout_seconds: float,
) -> str:
    """POST /v1/chat/completions. 400 → model muhtemelen yüklü değil → load + retry."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 8000,
        "temperature": 0.3,
    }
    url = f"{host}/v1/chat/completions"
    r = await client.post(url, json=payload, timeout=timeout_seconds)
    if r.status_code == 400:
        log.info("lmstudio.model_not_loaded", model=model, action="lms_load")
        await asyncio.to_thread(_lmstudio_load_model, model)
        r = await client.post(url, json=payload, timeout=timeout_seconds)
    if r.status_code != 200:
        raise _LMStudioUnavailableError(f"lmstudio HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    content = (data["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise RuntimeError(f"LM Studio returned empty content for model {model!r}")
    return content


async def _synthesize_lmstudio(prompt: str, *, model: str, timeout_seconds: float) -> str:
    host = _resolve_lmstudio_host()
    timeout = httpx.Timeout(timeout_seconds, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if not await _lmstudio_server_up(client, host):
            log.info("lmstudio.server_down", action="auto_start")
            await asyncio.to_thread(_lmstudio_start_server)
            if not await _lmstudio_server_up(client, host):
                raise _LMStudioUnavailableError("server still down after lms server start")
        out = await _lmstudio_call(
            client, host=host, model=model, prompt=prompt, timeout_seconds=timeout_seconds
        )
    log.info(
        "lmstudio.ok",
        chars_in=len(prompt),
        chars_out=len(out),
        model=model,
    )
    return out


# ── Ollama path ───────────────────────────────────────────────────────


@retry(
    # Sadece ConnectError + OSError (fast-fail). ReadTimeout retry'lemiyoruz
    # — uzun bir generation yarıda kesilirse retry baştan başlar, 2x burn.
    retry=retry_if_exception_type((httpx.ConnectError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def _synthesize_ollama(prompt: str, *, model: str, timeout_seconds: float) -> str:
    timeout = httpx.Timeout(timeout_seconds, connect=10.0)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    async with httpx.AsyncClient(base_url=_resolve_ollama_host(), timeout=timeout) as client:
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()

    content = ((data.get("message") or {}).get("content") or "").strip()
    if not content:
        raise RuntimeError(f"Ollama returned empty content; payload keys={list(data)}")
    log.info(
        "ollama.ok",
        chars_in=len(prompt),
        chars_out=len(content),
        model=model,
    )
    return content


# ── Public dispatcher ─────────────────────────────────────────────────


async def synthesize_with_local_llm(
    prompt: str,
    *,
    model: str | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Send prompt to local LLM (LM Studio tercih, Ollama fallback).

    Drop-in replacement for ``synthesize_with_claude`` in stages where
    reasoning gerekmiyor (transcript reformatlama, light translation).

    Provider seçimi:
      - ``LOCAL_LLM_PROVIDER=auto`` (default) — LM Studio dene, fail → Ollama
      - ``LOCAL_LLM_PROVIDER=lmstudio`` — sadece LM Studio (fail = exception)
      - ``LOCAL_LLM_PROVIDER=ollama`` — sadece Ollama
    """
    if not prompt or not prompt.strip():
        raise ValueError("Cannot send empty prompt to local LLM")

    timeout = float(timeout_seconds if timeout_seconds is not None else _DEFAULT_TIMEOUT_SECONDS)
    provider = _resolve_provider()

    if provider in ("auto", "lmstudio"):
        lm_model = model or _resolve_lmstudio_model()
        try:
            return await _synthesize_lmstudio(prompt, model=lm_model, timeout_seconds=timeout)
        except _LMStudioUnavailableError as e:
            if provider == "lmstudio":
                raise
            log.info("local_llm.fallback", from_="lmstudio", to="ollama", reason=str(e)[:120])

    ol_model = model or _resolve_ollama_model()
    return await _synthesize_ollama(prompt, model=ol_model, timeout_seconds=timeout)

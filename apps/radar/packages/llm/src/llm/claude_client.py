"""Anthropic Claude CLI wrapper (Phase 12-ii brief generation).

Phase 10-i.5 mimarisini koruyarak: API key yok, sadece subscription.
``claude -p`` Claude Code'un non-interactive prompt modu — Max
subscription kullanır, 1M context'e erişir. Mirror of gemini_client
pattern; tek farklılık CLI flag (`-p` vs `--prompt`).

Phase 29: subprocess hardening flag'leri eklendi (aşağıda ``_HARDENING_FLAGS``).
Heavy bootstrap (10+ MCP server, skill loading, hook'lar, auto-memory)
tek-shot text görevlerinde 600sn timeout'u aşıyordu. ``--bare`` ideal olur
ama OAuth/keychain'i kapattığı için subscription auth ile uyumsuz.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import structlog

log = structlog.get_logger()

# Brief generation 30-90 sn beklenir; 600 sn üst sınır rate-limit/network
# bottleneck'lerine yastık verir.
_CLAUDE_TIMEOUT_SECONDS = 600

# Phase 29: subprocess'i kullanıcının tüm ~/.claude ortamını yüklemeden
# çalıştır. Subscription auth (OAuth/keychain) korunur — sadece
# MCP/skill/tool/session-state yan etkileri kapatılır.
_HARDENING_FLAGS = (
    "--output-format",
    "text",
    "--no-session-persistence",
    "--tools",
    "",
    "--disable-slash-commands",
    "--strict-mcp-config",
)


def _run_claude(prompt: str, *, timeout_seconds: int = _CLAUDE_TIMEOUT_SECONDS) -> str:
    """Sync helper for ``asyncio.to_thread`` — returns claude stdout.

    Raises ``FileNotFoundError`` if CLI yok PATH'te, ``RuntimeError`` on
    non-zero exit. Windows'ta `claude.cmd` shim'i shutil.which ile çözülür
    (gemini_client ile aynı pattern).

    **Stdin pattern**: prompt argv yerine stdin üzerinden geçirilir. Sebep:
    Windows CMD argv ~32KB sınırı (``claude.cmd`` batch shim bu sınırı
    miras alır), brief prompt'u 30KB+ olabilir. Stdin'in size limit'i
    pratik olarak yok.
    """
    cli = shutil.which("claude")
    if cli is None:
        raise FileNotFoundError("claude CLI not in PATH")
    proc = subprocess.run(
        [cli, "-p", *_HARDENING_FLAGS],  # -p without prompt → reads from stdin
        input=prompt,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI failed (rc={proc.returncode}): "
            f"{proc.stderr or proc.stdout or '(no output)'}"
        )
    return proc.stdout


async def synthesize_with_claude(prompt: str, *, timeout_seconds: int | None = None) -> str:
    """Send a prompt to ``claude -p`` and return its plaintext response.

    Phase 12-ii brief generation için kullanılır — input'un ~80 makale
    Türkçe gündem brief'i üretmek üzere). 1M context Max subscription'a
    bağlanır.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Cannot send empty prompt to claude")

    timeout = timeout_seconds if timeout_seconds is not None else _CLAUDE_TIMEOUT_SECONDS
    stdout = await asyncio.to_thread(_run_claude, prompt, timeout_seconds=timeout)
    log.info("claude.ok", chars_in=len(prompt), chars_out=len(stdout))
    return stdout

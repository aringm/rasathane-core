"""OpenAI Codex CLI wrapper for code-review second opinion.

Uses ``subprocess.run`` wrapped in ``asyncio.to_thread`` (the same pattern
``synthesis.mindmap`` uses). Plain Python wrapper around ``codex --prompt``.

Phase 6 invokes this for the "second opinion" pass on GitHub repo analyses
(after Claude/Gemini gives the primary read). Anthropic+OpenAI have
different blind spots, so the composition is genuinely additive.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import structlog

log = structlog.get_logger()


def _run_codex(prompt: str, timeout_seconds: int) -> tuple[int, str, str]:
    """Sync helper for ``asyncio.to_thread``.

    Windows'ta `codex.cmd` shim'i `shutil.which` ile çözülür (PATHEXT okur).
    `subprocess.run(shell=False)` `.cmd`/`.bat` uzantılarını otomatik aramaz.
    claude_client.py:36'daki pattern.
    """
    cli = shutil.which("codex")
    if cli is None:
        raise FileNotFoundError("codex CLI not in PATH")
    proc = subprocess.run(
        [cli, "exec", "--full-auto", prompt],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


async def review_with_codex(
    prompt: str,
    *,
    timeout_seconds: int = 600,
) -> str:
    """Send a prompt to ``codex exec`` and return its plaintext response.

    Raises ``RuntimeError`` if codex is missing, times out, or returns a
    non-zero exit code.
    """
    if not prompt or not prompt.strip():
        raise ValueError("Cannot send empty prompt to codex")

    rc, stdout, stderr = await asyncio.to_thread(_run_codex, prompt, timeout_seconds)
    if rc != 0:
        raise RuntimeError(f"codex CLI failed (rc={rc}): {stderr or stdout or '(no output)'}")
    log.info("codex.ok", chars_in=len(prompt), chars_out=len(stdout))
    return stdout

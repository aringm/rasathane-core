"""Google Gemini CLI wrapper for the 2M-context ``LARGE_CODEBASE`` task.

Phase 6 routes here when a Repomix dump exceeds Claude Opus's 200K token
budget (~180K with safety buffer). Uses ``subprocess.run`` wrapped in
``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import structlog

log = structlog.get_logger()


def _run_gemini(prompt: str, timeout_seconds: int) -> tuple[int, str, str]:
    """Sync helper for ``asyncio.to_thread``.

    Windows'ta `gemini.cmd` shim'i `shutil.which` ile çözülür (PATHEXT okur).
    `subprocess.run(shell=False)` `.cmd`/`.bat` uzantılarını otomatik aramaz.
    claude_client.py:36'daki pattern.
    """
    cli = shutil.which("gemini")
    if cli is None:
        raise FileNotFoundError("gemini CLI not in PATH")
    proc = subprocess.run(
        [cli, "--prompt", prompt],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
        encoding="utf-8",
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


async def analyze_with_gemini(
    prompt: str,
    *,
    timeout_seconds: int = 900,
) -> str:
    """Send a prompt to ``gemini`` CLI and return its plaintext response."""
    if not prompt or not prompt.strip():
        raise ValueError("Cannot send empty prompt to gemini")

    rc, stdout, stderr = await asyncio.to_thread(_run_gemini, prompt, timeout_seconds)
    if rc != 0:
        raise RuntimeError(f"gemini CLI failed (rc={rc}): {stderr or stdout or '(no output)'}")
    log.info("gemini.ok", chars_in=len(prompt), chars_out=len(stdout))
    return stdout

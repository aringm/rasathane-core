"""GitHub repo ingestion: metadata via REST API + Repomix dump via subprocess.

Two-step shape:
    1. ``fetch_repo_metadata(url)`` — public GitHub REST API (httpx).
       ``GITHUB_TOKEN`` env optional; raises rate-limit error without it
       on aggressive use, but works for ad-hoc analysis.
    2. ``run_repomix(repo_url, output_path)`` — pnpm exec repomix --remote
       (workspace dev dep). Output is a single-file repo dump for LLM input.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

log = structlog.get_logger()

GITHUB_API_BASE = "https://api.github.com"
HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# Char-based token estimate is fine for routing decisions (target threshold
# ~180K tokens). Chars-per-token ratio depends on language/code mix; using
# 3.5 conservative for code-heavy repos where tokenizers split aggressively.
CHARS_PER_TOKEN = 3.5


@dataclass(frozen=True)
class RepoMetadata:
    owner: str
    name: str
    full_name: str  # "owner/repo"
    description: str | None
    primary_language: str | None
    stars: int
    forks: int
    default_branch: str
    url: str  # canonical https URL


_GITHUB_URL_RE = re.compile(r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/?#]+)")


def parse_github_url(url: str) -> tuple[str, str]:
    """Parse https://github.com/owner/repo[/...] → (owner, repo)."""
    m = _GITHUB_URL_RE.match(url.rstrip("/"))
    if not m:
        raise ValueError(f"Not a GitHub repo URL: {url!r}")
    return m["owner"], m["repo"].removesuffix(".git")


async def fetch_repo_metadata(url: str) -> RepoMetadata:
    """Fetch repo metadata via GitHub REST API."""
    owner, repo = parse_github_url(url)
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(f"{GITHUB_API_BASE}/repos/{owner}/{repo}", headers=headers)
        response.raise_for_status()
        data = response.json()

    return RepoMetadata(
        owner=owner,
        name=repo,
        full_name=data.get("full_name", f"{owner}/{repo}"),
        description=data.get("description"),
        primary_language=data.get("language"),
        stars=int(data.get("stargazers_count") or 0),
        forks=int(data.get("forks_count") or 0),
        default_branch=data.get("default_branch", "main"),
        url=f"https://github.com/{owner}/{repo}",
    )


def _run_repomix(
    repo_url: str,
    output_path: Path,
    project_root: Path,
    timeout_seconds: int,
) -> tuple[int, str, str]:
    """Sync helper invoked via ``asyncio.to_thread``.

    Windows'ta `pnpm.cmd` shim'i `shutil.which` ile çözülür (PATHEXT okur).
    `subprocess.run(shell=False)` `.cmd`/`.bat` uzantılarını otomatik aramaz —
    sadece `.exe`. claude_client.py:36'daki pattern.
    """
    cli = shutil.which("pnpm")
    if cli is None:
        raise FileNotFoundError(
            "pnpm CLI bulunamadı (PATH'te yok). GitHub repo analizi için "
            "pnpm gerekli — kurulum: https://pnpm.io/installation"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            cli,
            "--dir",
            str(project_root),
            "exec",
            "repomix",
            "--remote",
            repo_url,
            "--output",
            str(output_path),
            "--style",
            "plain",
            "--no-security-check",
        ],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        shell=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


async def run_repomix(
    repo_url: str,
    *,
    output_path: Path,
    project_root: Path,
    timeout_seconds: int = 600,
) -> Path:
    """Dump a remote repo to a single text file via Repomix."""
    rc, stdout, stderr = await asyncio.to_thread(
        _run_repomix, repo_url, output_path, project_root, timeout_seconds
    )
    if rc != 0:
        raise RuntimeError(f"repomix failed (rc={rc}): {stderr or stdout or '(no output)'}")
    log.info(
        "github.repomix.ok",
        repo=repo_url,
        output=str(output_path),
    )
    return output_path


def estimate_tokens(text_or_chars: int | str) -> int:
    """Char-based token estimate (conservative ratio 3.5 for code-heavy text)."""
    chars = text_or_chars if isinstance(text_or_chars, int) else len(text_or_chars)
    return int(chars / CHARS_PER_TOKEN)

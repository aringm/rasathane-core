"""Console entry point — runs the MCP server over stdio.

Claude Desktop launches us via stdio (its native local-MCP transport).
Configure in ``%APPDATA%\\Claude\\claude_desktop_config.json`` (Windows)
or ``~/Library/Application Support/Claude/claude_desktop_config.json``
(macOS) — see the project HANDOFF.md for the exact JSON snippet.

Order matters: ``configure_for_mcp_stdio`` MUST run before importing
``server`` so the module-level ``log = structlog.get_logger()`` and any
lifespan log calls are bound to stderr from the very first emit.
"""

from __future__ import annotations

import shutil
import subprocess

import structlog

from rasathane_mcp._logging import configure_for_mcp_stdio

configure_for_mcp_stdio()

from rasathane_mcp.server import mcp  # noqa: E402 — must follow logging setup

log = structlog.get_logger(__name__)

_DOCKER_CONTAINERS = ("rasathane-postgres-1", "rasathane-redis-1")


def _ensure_docker_services() -> None:
    """Lazy-start required Docker containers on MCP attach.

    Compose policy restart=no so containers don't auto-start at host boot.
    When Claude Desktop spawns this MCP, ensure postgres+redis are running
    before the server reaches mcp.run() (tools hit the DB on first call).

    Best-effort: docker CLI absent or `docker start` non-zero exit logs
    and continues — MCP attach must not block on Docker.
    """
    docker = shutil.which("docker")
    if docker is None:
        log.warning("docker.ensure.skip", reason="docker CLI not on PATH")
        return
    try:
        result = subprocess.run(
            [docker, "start", *_DOCKER_CONTAINERS],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        log.warning("docker.ensure.timeout", containers=_DOCKER_CONTAINERS)
        return
    except OSError as e:
        log.warning("docker.ensure.os_error", error=str(e))
        return
    if result.returncode != 0:
        log.warning(
            "docker.ensure.failed",
            stderr=result.stderr.strip(),
            containers=_DOCKER_CONTAINERS,
        )
    else:
        log.info("docker.ensure.ok", containers=_DOCKER_CONTAINERS)


def main() -> None:
    """Entry point registered in pyproject.toml as ``rasathane-mcp``."""
    _ensure_docker_services()
    mcp.run()


if __name__ == "__main__":
    main()

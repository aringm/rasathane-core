"""Stdio-safe logging setup for the Rasathane MCP server.

MCP stdio transport reserves stdin/stdout for JSON-RPC. Anything else
written to stdout corrupts the framing — Claude Desktop surfaces errors
like ``Unexpected non-whitespace character after JSON at position N``
and the connection is silently dropped.

Two stdout offenders to silence:

1. **structlog default factory**. ``structlog.get_config()['logger_factory']``
   is ``PrintLoggerFactory`` (binds to ``sys.stdout``) until reconfigured.
   Every ``log.info("dashboard.start.ok", ...)`` would otherwise write
   ``2025-...`` to stdout — exactly the pattern that breaks JSON parsing
   at column 5 (the ``-`` after ``2025``).

2. **stdlib logging root handlers**. uvicorn, asyncio, sqlalchemy emit
   through the stdlib ``logging`` module. uvicorn's own logging config
   targets stderr by default, but if a third-party module installs a
   stdout ``StreamHandler`` we strip it.

This setup must run **before any structlog logger is materialized** —
``cli.py`` calls it as the very first import-time side effect so even
``server.py``'s module-level ``log = structlog.get_logger()`` picks up
the patched factory.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_for_mcp_stdio() -> None:
    """Pin every log channel to stderr. Idempotent."""
    # 1. structlog → stderr.
    # WriteLoggerFactory is the modern equivalent of PrintLoggerFactory and
    # accepts a ``file`` kwarg, so we can target stderr explicitly.
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.KeyValueRenderer(
                key_order=["timestamp", "level", "event"],
                drop_missing=True,
            ),
        ],
        logger_factory=structlog.WriteLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # 2. stdlib logging → stderr. Drop any handler bound to stdout, install
    # a stderr handler if one isn't already there.
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            root.removeHandler(handler)
    if not any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in root.handlers
    ):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.WARNING)

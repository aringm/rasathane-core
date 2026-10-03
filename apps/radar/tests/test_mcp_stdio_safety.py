"""Guards against MCP stdio corruption.

The MCP transport reserves stdout for JSON-RPC. Anything else written
there breaks Claude Desktop's parser with errors like
``Unexpected non-whitespace character after JSON at position N``.

These tests pin the contract: after ``configure_for_mcp_stdio()`` runs,
no module — structlog, stdlib logging, or anything that delegates to
them — must touch stdout. If a future PR re-introduces a stdout-writing
log channel, this suite catches it before Claude Desktop does.

We bypass pytest's ``capsys``/``capfd`` because structlog's
``WriteLoggerFactory`` binds ``sys.stderr`` at configure time and caches
the reference; pytest's capture fixtures swap streams at a different
layer and produce false negatives. ``redirect_stdout``/``redirect_stderr``
inside each test guarantees the factory and the assertion see the same
buffer.
"""

from __future__ import annotations

import io
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout

import structlog
from rasathane_mcp._logging import configure_for_mcp_stdio


def test_structlog_writes_only_to_stderr() -> None:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        configure_for_mcp_stdio()
        log = structlog.get_logger("stdio-safety-structlog")
        log.info("hello-stdio", payload={"x": 1})

    assert out_buf.getvalue() == "", f"stdout leak: {out_buf.getvalue()!r}"
    assert "hello-stdio" in err_buf.getvalue()


def test_stdlib_logging_writes_only_to_stderr() -> None:
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        configure_for_mcp_stdio()
        logger = logging.getLogger("uvicorn-redirect-test")
        logger.warning("uvicorn-style message")

    assert out_buf.getvalue() == "", f"stdout leak: {out_buf.getvalue()!r}"
    assert "uvicorn-style message" in err_buf.getvalue()


def test_structlog_factory_targets_stderr() -> None:
    """The configured factory must produce a logger pinned to the live stderr."""
    configure_for_mcp_stdio()
    factory = structlog.get_config()["logger_factory"]
    logger = factory()
    stream = getattr(logger, "_file", None)
    assert stream is sys.stderr, f"structlog factory writes to {stream!r}; expected sys.stderr"


def test_root_logger_has_no_stdout_handler() -> None:
    configure_for_mcp_stdio()
    root = logging.getLogger()
    stdout_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
    ]
    assert stdout_handlers == [], f"stdout-bound stdlib handlers leak: {stdout_handlers!r}"


def test_setup_is_idempotent() -> None:
    """Calling twice must not double-stack handlers on stderr."""
    configure_for_mcp_stdio()
    configure_for_mcp_stdio()
    root = logging.getLogger()
    stderr_handlers = [
        h for h in root.handlers if isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
    ]
    assert len(stderr_handlers) == 1, (
        f"expected exactly one stderr handler; got {len(stderr_handlers)}"
    )

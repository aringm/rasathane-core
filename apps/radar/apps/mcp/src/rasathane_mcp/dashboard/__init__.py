"""Rasathane dashboard — local web UI bundled with the MCP server.

Boots a FastAPI/uvicorn server inside the MCP process via a FastMCP
lifespan, mirroring Serena's pattern: stdio talks to Claude Desktop,
HTTP talks to the user's browser, both share the same DB connection
pool and event loop.
"""

from rasathane_mcp.dashboard.lifespan import dashboard_lifespan

__all__ = ["dashboard_lifespan"]

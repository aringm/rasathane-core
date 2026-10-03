"""Rasathane MCP server package.

Exposes the data layer (sources, articles, embeddings, briefs, emsals) as
MCP tools so Claude Desktop (or any MCP client) can drive interactive
analysis without a stand-alone LLM API key.
"""

from rasathane_mcp.server import mcp

__all__ = ["mcp"]

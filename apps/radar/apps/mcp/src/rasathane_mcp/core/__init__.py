"""Shared business logic between the MCP tools and the FastAPI dashboard.

Both the MCP server (``rasathane_mcp.server``) and the dashboard
(``rasathane_mcp.dashboard.app``) read from this package. Keeping
queries, serializers, and filesystem paths in one place prevents drift —
without it, the dashboard's article-list endpoint would inevitably fall
out of sync with the MCP ``recent_articles`` tool.
"""

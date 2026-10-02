"""LLM helpers for Rasathane (key-free).

After the Phase 10-i cleanup this package holds only:
    - ``embeddings.py``: Ollama HTTP, local, key-free
    - ``codex_client.py``: ``codex`` CLI subprocess wrapper (subscription)
    - ``gemini_client.py``: ``gemini`` CLI subprocess wrapper (subscription)

The Anthropic SDK client + task router were removed; the interactive
analysis path now flows through Claude Desktop via the MCP server
(``apps/mcp``). A future Phase 10-ii will add a ``claude`` CLI wrapper
in the same subprocess style as codex/gemini, for autonomous brief
generation that still avoids API keys.
"""

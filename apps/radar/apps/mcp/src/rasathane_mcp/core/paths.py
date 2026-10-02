"""Filesystem layout constants for the Rasathane backend.

Both the MCP server tools and the dashboard endpoints read briefs out of
``archive/`` and serve ``data/feeds.yaml`` as a resource. Centralising
the constants here means a future repo-layout change touches one file.
"""

from __future__ import annotations

from pathlib import Path

# apps/mcp/src/rasathane_mcp/core/paths.py → walk up 5 to reach repo root.
REPO_ROOT = Path(__file__).resolve().parents[5]
ARCHIVE_ROOT = REPO_ROOT / "archive"
FEEDS_YAML = REPO_ROOT / "data" / "feeds.yaml"


def data_dir() -> Path:
    """Workspace-relative ``data/`` dizini (presets, profiles, vs).

    Phase 36-ii: audio preset storage `data/audio_presets.json` için
    callable helper — REPO_ROOT sabitinden tüketici lazy çözer ki
    test'ler monkeypatch ile ezebilsin.
    """
    return REPO_ROOT / "data"

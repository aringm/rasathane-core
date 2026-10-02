"""Smoke tests — verifies package wiring + model schema after the Phase 10-i cleanup.

Removed packages (api, synthesis, tts, output) are no longer imported.
"""

from __future__ import annotations


def test_worker_version() -> None:
    from worker import __version__

    assert __version__ == "0.1.0"


def test_store_models_import() -> None:
    from store.models import Article, Asset, Brief, Cluster, Source, User

    for model in (User, Source, Article, Cluster, Brief, Asset):
        assert model.__tablename__ is not None


def test_store_embedding_dim_is_bge_m3_compatible() -> None:
    from store import EMBEDDING_DIM

    # 1024 dim covers BAAI/bge-m3 and Alibaba qwen3-embedding:0.6b
    # (currently active default in apps/mcp + worker `pulse embed`).
    assert EMBEDDING_DIM == 1024


def test_kept_packages_importable() -> None:
    import ingestion  # noqa: F401
    import llm  # noqa: F401
    import rasathane_mcp  # noqa: F401

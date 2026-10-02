from __future__ import annotations

from ytcore.pipeline.checkpoint import get_checkpointer


def test_sqlite_checkpointer(tmp_path):
    cp = get_checkpointer(tmp_path / "cp.sqlite")
    # LangGraph BaseCheckpointSaver arayüzü
    assert hasattr(cp, "put") and hasattr(cp, "get_tuple")

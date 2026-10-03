from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def get_checkpointer(db_path: Path) -> SqliteSaver:
    """SQLite checkpoint (resmî olarak 'experimentation/local' — A14 düzeltme).

    Abstraksiyon: batch/async worker gelince PostgresSaver'a geçilir
    (muhakeme gömülü-PG emsali). Faz 0'da tek-thread yeterli.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    return SqliteSaver(conn)

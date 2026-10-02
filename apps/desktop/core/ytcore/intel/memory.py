from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class Ani:
    metin: str
    meta: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class MemoryStore(Protocol):
    def ekle(self, metin: str, meta: dict[str, str]) -> None: ...

    def ara(self, sorgu: str, k: int = 5) -> list[Ani]: ...


class FakeMemoryStore:
    """Hermetik in-memory bellek (token-overlap retrieval). Test + exe selftest.

    LanceMemoryStore ile aynı kontrat. Alakasız anı döndürmez (en az 1 ortak token).
    """

    def __init__(self) -> None:
        self._anilar: list[Ani] = []

    def ekle(self, metin: str, meta: dict[str, str]) -> None:
        if metin.strip():
            self._anilar.append(Ani(metin=metin, meta=dict(meta)))

    def ara(self, sorgu: str, k: int = 5) -> list[Ani]:
        s = set(sorgu.lower().split())
        if not s or not self._anilar:
            return []
        ortak = [(a, len(s & set(a.metin.lower().split()))) for a in self._anilar]
        ilgili = sorted((a for a in ortak if a[1] > 0), key=lambda x: -x[1])
        return [a for a, _ in ilgili[:k]]


class LanceMemoryStore:
    """bge-m3 + ayrı LanceDB table episodik bellek (torch-free). Index'ten ayrı yaşar."""

    def __init__(self, taban: Path | None = None) -> None:
        from ytcore.config import get_config

        self._taban = (taban or get_config().index_base) / "memory"
        self._taban.mkdir(parents=True, exist_ok=True)
        self._tablo: Any = None
        self._db: Any = None

    def _baglan(self) -> Any:
        import lancedb

        if self._db is None:
            self._db = lancedb.connect(str(self._taban))
        return self._db

    def _mevcut(self) -> Any:
        if self._tablo is not None:
            return self._tablo
        db = self._baglan()
        # list_tables().tables (table_names() deprecated >=0.30; ListTablesResponse — düz liste
        # değil, `.tables` şart — index.py ile aynı tuzak, empirik doğrulandı lancedb 0.33).
        if "anilar" in db.list_tables().tables:
            self._tablo = db.open_table("anilar")
        return self._tablo

    def _olustur(self, boyut: int) -> Any:
        import pyarrow as pa

        sema = pa.schema(
            [
                pa.field("vektor", pa.list_(pa.float32(), boyut)),
                pa.field("metin", pa.string()),
                pa.field("video_id", pa.string()),
            ]
        )
        self._tablo = self._baglan().create_table("anilar", schema=sema)
        return self._tablo

    def ekle(self, metin: str, meta: dict[str, str]) -> None:
        if not metin.strip():
            return
        from ytcore.infra.embedding import embedding_al

        v = [float(x) for x in embedding_al().embed([metin])[0]]
        t = self._mevcut()
        if t is None:
            t = self._olustur(len(v))
        t.add([{"vektor": v, "metin": metin, "video_id": meta.get("video_id", "")}])

    def ara(self, sorgu: str, k: int = 5) -> list[Ani]:
        from ytcore.infra.embedding import embedding_al

        t = self._mevcut()
        if t is None or t.count_rows() == 0:
            return []
        qv = [float(x) for x in embedding_al().embed([sorgu])[0]]
        return [
            Ani(metin=r["metin"], meta={"video_id": r["video_id"]})
            for r in t.search(qv, vector_column_name="vektor").limit(k).to_list()
        ]


def memory_al() -> MemoryStore:
    """YT_MEMORY_FIXTURE set ise FakeMemoryStore (hermetik), değilse LanceMemoryStore.

    NOT (review tur-4): YT_EMBED_FIXTURE'a kuplajlanmaz (index_al ile aynı gerekçe — exe selftest
    gerçek LanceDB bellek tablosunu doğrulasın)."""
    if os.environ.get("YT_MEMORY_FIXTURE", "").strip():
        return FakeMemoryStore()
    return LanceMemoryStore()

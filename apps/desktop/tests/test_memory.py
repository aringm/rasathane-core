from __future__ import annotations

import pytest
from ytcore.intel.memory import FakeMemoryStore, memory_al


def test_fake_memory_ekle_ara(monkeypatch):
    monkeypatch.setenv("YT_MEMORY_FIXTURE", "1")
    m = memory_al()
    assert isinstance(m, FakeMemoryStore)
    m.ekle("Sözleşme hukuku müvekkil için önemli.", {"video_id": "v1"})
    m.ekle("Tazminat davası açıldı.", {"video_id": "v2"})
    sonuc = m.ara("sözleşme konusu", k=1)
    assert len(sonuc) == 1
    assert "Sözleşme" in sonuc[0].metin
    assert sonuc[0].meta["video_id"] == "v1"


def test_fake_memory_bos_ara(monkeypatch):
    monkeypatch.setenv("YT_MEMORY_FIXTURE", "1")
    m = memory_al()
    assert m.ara("herhangi", k=5) == []  # boş bellek → boş (sessiz başarı değil)


def test_fake_memory_alakasiz_donmez(monkeypatch):
    monkeypatch.setenv("YT_MEMORY_FIXTURE", "1")
    m = memory_al()
    m.ekle("Tazminat davası açıldı.", {"video_id": "v2"})
    # Hiç ortak token yok → alakasız anı döndürülmez.
    assert m.ara("astronomi gezegen", k=5) == []


def test_fake_memory_bos_metin_eklenmez(monkeypatch):
    monkeypatch.setenv("YT_MEMORY_FIXTURE", "1")
    m = memory_al()
    m.ekle("   ", {"video_id": "v"})
    assert m.ara("herhangi", k=5) == []


@pytest.mark.ollama
def test_lance_memory_gercek(tmp_path, monkeypatch):
    monkeypatch.delenv("YT_MEMORY_FIXTURE", raising=False)
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")
    from ytcore.intel.memory import LanceMemoryStore

    m = LanceMemoryStore(taban=tmp_path / "_index")
    m.ekle("Sözleşme feshi davası kazanıldı.", {"video_id": "v1"})
    sonuc = m.ara("sözleşme feshi", k=1)
    assert len(sonuc) == 1
    assert sonuc[0].meta["video_id"] == "v1"

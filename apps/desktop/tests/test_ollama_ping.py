from __future__ import annotations

import pytest
from ytcore.local.ollama_ping import _embedding_modeli_mi, ollama_erisilebilir, ollama_ping


@pytest.mark.skipif(not ollama_erisilebilir(), reason="Ollama erişilemez")
def test_ollama_real_round_trip():
    r = ollama_ping()
    assert r.basarili is True
    assert r.sure_ms >= 0
    assert isinstance(r.yanit, str) and len(r.yanit) > 0


@pytest.mark.parametrize(
    "ad,beklenen",
    [
        ("bge-m3:latest", True),  # embedding ama adında 'embedding' yok — yine de elenmeli
        ("qwen3-embedding:8b", True),
        ("nomic-embed-text", True),
        ("qwen2.5:14b", False),
        ("gemma4:12b", False),
    ],
)
def test_embedding_modeli_filtre(ad, beklenen):
    # bge-m3 chat-fallback olarak seçilip /api/chat'te 400 vermemeli (regresyon).
    assert _embedding_modeli_mi(ad) is beklenen

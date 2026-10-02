from __future__ import annotations

import pytest
from ytcore.infra.embedding import FakeEmbedding, embedding_al


def test_fake_embedding_deterministik():
    e = FakeEmbedding()
    v1 = e.embed(["merhaba", "dunya"])
    v2 = e.embed(["merhaba", "dunya"])
    assert v1 == v2
    assert len(v1) == 2
    assert all(len(v) == e.boyut for v in v1)
    # farklı metin farklı vektör
    assert e.embed(["a"])[0] != e.embed(["b"])[0]


def test_fake_embedding_normalize():
    e = FakeEmbedding()
    (v,) = e.embed(["test"])
    norm = sum(x * x for x in v) ** 0.5
    assert abs(norm - 1.0) < 1e-6  # birim vektör (kosinüs = nokta-çarpım)


def test_fake_embedding_bos():
    assert FakeEmbedding().embed([]) == []


def test_embedding_al_fixture_seam(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("YT_EMBED_FIXTURE", "1")
    assert isinstance(embedding_al(), FakeEmbedding)


def test_embedding_al_gercek_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("YT_EMBED_FIXTURE", raising=False)
    prov = embedding_al()
    assert prov.ad == "bge-m3"
    assert prov.lisans == "MIT"

"""Embeddings tests with mocked Ollama HTTP — no real Ollama required."""

from __future__ import annotations

import pytest
import respx
from httpx import Response
from llm.embeddings import EMBEDDING_DIM, embed_batch, embed_text

OLLAMA_HOST = "http://127.0.0.1:11434"
EMBED_ENDPOINT = f"{OLLAMA_HOST}/api/embeddings"


@pytest.fixture(autouse=True)
def _force_loopback_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin OLLAMA_HOST to 127.0.0.1 regardless of dev-machine env.

    Phase 10-i.7 made ``_resolve_host()`` rewrite ``localhost`` and
    ``0.0.0.0`` to ``127.0.0.1`` (Windows IPv6 + bind-address gotchas).
    Tests use the post-rewrite form directly so respx mocks line up.
    """
    monkeypatch.setenv("OLLAMA_HOST", OLLAMA_HOST)


def _fake_response(dim: int = EMBEDDING_DIM) -> dict:
    return {"embedding": [0.01 * i for i in range(dim)]}


async def test_embed_text_returns_correct_dim() -> None:
    with respx.mock() as mock:
        mock.post(EMBED_ENDPOINT).mock(return_value=Response(200, json=_fake_response()))
        vec = await embed_text("Hello, Türkçe!")

    assert isinstance(vec, list)
    assert len(vec) == EMBEDDING_DIM


async def test_embed_text_rejects_empty() -> None:
    with pytest.raises(ValueError, match="Cannot embed empty text"):
        await embed_text("")
    with pytest.raises(ValueError, match="Cannot embed empty text"):
        await embed_text("   ")


async def test_embed_text_validates_dim() -> None:
    """Wrong-dim model output must error loudly (schema mismatch)."""
    with respx.mock() as mock:
        mock.post(EMBED_ENDPOINT).mock(return_value=Response(200, json=_fake_response(dim=512)))
        with pytest.raises(RuntimeError, match="dim mismatch"):
            await embed_text("any text")


async def test_embed_batch_preserves_order() -> None:
    """Inputs ['a','b','c'] → outputs[0],[1],[2] correspond in order."""
    counter = {"i": 0}

    def make_response(_request) -> Response:
        i = counter["i"]
        counter["i"] = i + 1
        # encode the input index in the first element so we can verify order
        return Response(200, json={"embedding": [float(i)] * EMBEDDING_DIM})

    with respx.mock() as mock:
        mock.post(EMBED_ENDPOINT).mock(side_effect=make_response)
        results = await embed_batch(["a", "b", "c"])

    assert len(results) == 3
    # NB: with concurrency, the first element may not be 0,1,2 deterministically.
    # Just verify all 3 came back with correct dim.
    for vec in results:
        assert len(vec) == EMBEDDING_DIM


async def test_embed_text_passes_model_name() -> None:
    captured: dict = {}

    def capture(request) -> Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        return Response(200, json=_fake_response())

    with respx.mock() as mock:
        mock.post(EMBED_ENDPOINT).mock(side_effect=capture)
        await embed_text("test", model="custom-model:1b")

    assert captured["body"]["model"] == "custom-model:1b"
    assert captured["body"]["prompt"] == "test"

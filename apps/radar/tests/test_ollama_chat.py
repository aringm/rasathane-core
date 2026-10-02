"""Phase 29: Hibrit local-LLM client tests (LM Studio tercih + Ollama fallback).

Public API: ``synthesize_with_local_llm`` provider'a göre dispatch eder.
LOCAL_LLM_PROVIDER env: auto | lmstudio | ollama.

Test edilenler:
  - Provider resolution (env defaults + invalid)
  - Empty prompt rejection (her provider'dan önce)
  - Host normalization (Windows IPv6/0.0.0.0 → 127.0.0.1)
  - Ollama path: payload shape, model override, whitespace strip, 5xx, empty
  - LM Studio path: server-up probe, payload shape, 400 → load+retry, empty
  - Auto-fallback: LM Studio unavailable → Ollama
  - Strict providers: lmstudio failure raises, ollama skips LM Studio
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from httpx import Response
from llm import ollama_chat

# ── Provider resolution ───────────────────────────────────────────────


def test_resolve_provider_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_LLM_PROVIDER", raising=False)
    assert ollama_chat._resolve_provider() == "auto"


@pytest.mark.parametrize("value", ["auto", "lmstudio", "ollama", "AUTO", " ollama "])
def test_resolve_provider_valid(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("LOCAL_LLM_PROVIDER", value)
    assert ollama_chat._resolve_provider() == value.lower().strip()


def test_resolve_provider_invalid_falls_back_to_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_PROVIDER", "vllm")
    assert ollama_chat._resolve_provider() == "auto"


# ── Model + host resolution ───────────────────────────────────────────


def test_resolve_ollama_model_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_MODEL_CHAT", raising=False)
    assert ollama_chat._resolve_ollama_model() == "qwen3:8b"


def test_resolve_ollama_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL_CHAT", "qwen3-coder:30b")
    assert ollama_chat._resolve_ollama_model() == "qwen3-coder:30b"


def test_resolve_lmstudio_model_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LMSTUDIO_MODEL_CHAT", raising=False)
    assert ollama_chat._resolve_lmstudio_model() == "google/gemma-4-26b-a4b"


def test_resolve_lmstudio_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LMSTUDIO_MODEL_CHAT", "qwen/qwen3.6-27b")
    assert ollama_chat._resolve_lmstudio_model() == "qwen/qwen3.6-27b"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("http://localhost:11434", "http://127.0.0.1:11434"),  # Windows IPv6 fix
        ("http://0.0.0.0:11434", "http://127.0.0.1:11434"),  # bind addr fix
        ("127.0.0.1:11434", "http://127.0.0.1:11434"),  # scheme prefix
        ("https://ollama.example:443", "https://ollama.example:443"),
    ],
)
def test_resolve_ollama_host_windows_gotchas(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", raw)
    assert ollama_chat._resolve_ollama_host() == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("http://127.0.0.1:1234", "http://127.0.0.1:1234"),
        ("http://localhost:1234", "http://127.0.0.1:1234"),
        ("http://0.0.0.0:1234", "http://127.0.0.1:1234"),
    ],
)
def test_resolve_lmstudio_host_windows_gotchas(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
) -> None:
    monkeypatch.setenv("LMSTUDIO_HOST", raw)
    assert ollama_chat._resolve_lmstudio_host() == expected


# ── Empty prompt (provider-agnostic) ──────────────────────────────────


@pytest.mark.asyncio
async def test_synthesize_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError, match="empty"):
        await ollama_chat.synthesize_with_local_llm("")
    with pytest.raises(ValueError, match="empty"):
        await ollama_chat.synthesize_with_local_llm("   \n\t  ")


# ── Ollama path (provider=ollama, no LM Studio probing) ───────────────


@pytest.fixture
def env_ollama_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")


@pytest.mark.asyncio
@respx.mock
async def test_ollama_payload_shape(env_ollama_only: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MODEL_CHAT", "qwen3:8b")
    route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "merhaba"}})
    )

    out = await ollama_chat.synthesize_with_local_llm("test")

    assert out == "merhaba"
    assert route.called
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "qwen3:8b"
    assert sent["messages"] == [{"role": "user", "content": "test"}]
    assert sent["stream"] is False


@pytest.mark.asyncio
@respx.mock
async def test_ollama_explicit_model_overrides_env(
    env_ollama_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OLLAMA_MODEL_CHAT", "qwen3:8b")
    route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "x"}})
    )

    await ollama_chat.synthesize_with_local_llm("p", model="qwen3-coder:30b")

    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "qwen3-coder:30b"


@pytest.mark.asyncio
@respx.mock
async def test_ollama_strips_whitespace(env_ollama_only: None) -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "  output  \n"}})
    )

    out = await ollama_chat.synthesize_with_local_llm("p")

    assert out == "output"


@pytest.mark.asyncio
@respx.mock
async def test_ollama_empty_content_raises(env_ollama_only: None) -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": ""}})
    )

    with pytest.raises(RuntimeError, match="empty content"):
        await ollama_chat.synthesize_with_local_llm("p")


@pytest.mark.asyncio
@respx.mock
async def test_ollama_5xx_raises(env_ollama_only: None) -> None:
    respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(500, json={"error": "model load failed"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await ollama_chat.synthesize_with_local_llm("p")


# ── LM Studio path (provider=lmstudio) ────────────────────────────────


@pytest.fixture
def env_lmstudio_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_PROVIDER", "lmstudio")
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
    # No-op subprocess hooks for LM Studio CLI calls
    monkeypatch.setattr(ollama_chat, "_lmstudio_start_server", lambda: None)
    monkeypatch.setattr(ollama_chat, "_lmstudio_load_model", lambda _model: None)


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_payload_shape(
    env_lmstudio_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LMSTUDIO_MODEL_CHAT", "google/gemma-4-26b-a4b")
    respx.get("http://127.0.0.1:1234/v1/models").mock(return_value=Response(200, json={"data": []}))
    route = respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={"choices": [{"message": {"content": "tamam"}}]},
        )
    )

    out = await ollama_chat.synthesize_with_local_llm("test")

    assert out == "tamam"
    assert route.called
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "google/gemma-4-26b-a4b"
    assert sent["messages"] == [{"role": "user", "content": "test"}]
    assert sent["stream"] is False
    assert sent["max_tokens"] == 8000


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_400_triggers_load_then_retry(
    env_lmstudio_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model yüklü değilse 400 → lms load → retry → 200."""
    load_called: dict[str, int] = {"n": 0}

    def fake_load(_model: str) -> None:
        load_called["n"] += 1

    monkeypatch.setattr(ollama_chat, "_lmstudio_load_model", fake_load)

    respx.get("http://127.0.0.1:1234/v1/models").mock(return_value=Response(200, json={"data": []}))
    # First call 400, second 200
    route = respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(
        side_effect=[
            Response(400, json={"error": "model not loaded"}),
            Response(200, json={"choices": [{"message": {"content": "yüklendi"}}]}),
        ]
    )

    out = await ollama_chat.synthesize_with_local_llm("p")

    assert out == "yüklendi"
    assert route.call_count == 2
    assert load_called["n"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_auto_starts_server_when_down(
    env_lmstudio_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server probe başarısız → lms server start → 2. probe başarılı → call."""
    start_calls: dict[str, int] = {"n": 0}

    def fake_start() -> None:
        start_calls["n"] += 1

    monkeypatch.setattr(ollama_chat, "_lmstudio_start_server", fake_start)

    # First /v1/models probe: ConnectError (server down)
    # Then post-start probe: 200
    probe_calls: dict[str, int] = {"n": 0}

    def models_handler(_request: Any) -> Response:
        probe_calls["n"] += 1
        if probe_calls["n"] == 1:
            raise httpx.ConnectError("connection refused")
        return Response(200, json={"data": []})

    respx.get("http://127.0.0.1:1234/v1/models").mock(side_effect=models_handler)
    respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )

    out = await ollama_chat.synthesize_with_local_llm("p")

    assert out == "ok"
    assert start_calls["n"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_lmstudio_only_raises_when_unavailable(
    env_lmstudio_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """provider=lmstudio + server permanently down → exception, no Ollama fallback."""

    def fake_start() -> None:
        raise ollama_chat._LMStudioUnavailableError("lms cli missing")

    monkeypatch.setattr(ollama_chat, "_lmstudio_start_server", fake_start)
    respx.get("http://127.0.0.1:1234/v1/models").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(ollama_chat._LMStudioUnavailableError):
        await ollama_chat.synthesize_with_local_llm("p")


# ── Auto provider (LM Studio first, Ollama fallback) ──────────────────


@pytest.fixture
def env_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_LLM_PROVIDER", "auto")
    monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(ollama_chat, "_lmstudio_start_server", lambda: None)
    monkeypatch.setattr(ollama_chat, "_lmstudio_load_model", lambda _model: None)


@pytest.mark.asyncio
@respx.mock
async def test_auto_prefers_lmstudio_when_up(env_auto: None) -> None:
    respx.get("http://127.0.0.1:1234/v1/models").mock(return_value=Response(200, json={"data": []}))
    lm_route = respx.post("http://127.0.0.1:1234/v1/chat/completions").mock(
        return_value=Response(200, json={"choices": [{"message": {"content": "lm"}}]})
    )
    ol_route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "ol"}})
    )

    out = await ollama_chat.synthesize_with_local_llm("p")

    assert out == "lm"
    assert lm_route.called
    assert not ol_route.called


@pytest.mark.asyncio
@respx.mock
async def test_auto_falls_back_to_ollama_when_lmstudio_unavailable(
    env_auto: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LM Studio server down + auto-start fail → Ollama'ya düş."""

    def fake_start() -> None:
        raise ollama_chat._LMStudioUnavailableError("cli not in path")

    monkeypatch.setattr(ollama_chat, "_lmstudio_start_server", fake_start)

    respx.get("http://127.0.0.1:1234/v1/models").mock(side_effect=httpx.ConnectError("refused"))
    ol_route = respx.post("http://127.0.0.1:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "fallback ok"}})
    )

    out = await ollama_chat.synthesize_with_local_llm("p")

    assert out == "fallback ok"
    assert ol_route.called

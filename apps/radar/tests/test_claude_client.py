"""Phase 29: subprocess hardening regression tests.

`synthesize_with_claude` `claude -p` subprocess'ini her zaman minimum
bootstrap (no MCP, no skill, no tool, no session persistence) ile
spawn etmeli. Test 600sn timeout regression'ını engelliyor — heavy
``~/.claude`` ortamı (10+ MCP, ~40 skill, hook'lar) tek-shot text
görevlerinde subprocess'i kilitliyordu.
"""

from __future__ import annotations

from typing import Any

import pytest
from llm import claude_client


class _FakeProc:
    def __init__(self, stdout: str = "ok", stderr: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _stub_subprocess(
    monkeypatch: pytest.MonkeyPatch, *, captured: dict[str, Any], proc: _FakeProc
) -> None:
    """Replace shutil.which + subprocess.run; capture argv passed to claude."""

    def fake_which(name: str) -> str:
        assert name == "claude"
        return r"C:\fake\claude.cmd"

    def fake_run(*args: Any, **kwargs: Any) -> _FakeProc:
        captured["argv"] = list(args[0])
        captured["input"] = kwargs.get("input")
        captured["timeout"] = kwargs.get("timeout")
        return proc

    monkeypatch.setattr(claude_client.shutil, "which", fake_which)
    monkeypatch.setattr(claude_client.subprocess, "run", fake_run)


@pytest.mark.asyncio
async def test_synthesize_passes_hardening_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """argv = [claude, -p, *_HARDENING_FLAGS] — sırayla, eksiksiz."""
    captured: dict[str, Any] = {}
    _stub_subprocess(monkeypatch, captured=captured, proc=_FakeProc(stdout="hi"))

    out = await claude_client.synthesize_with_claude("test prompt")

    assert out == "hi"
    argv = captured["argv"]
    assert argv[0].endswith("claude.cmd")
    assert argv[1] == "-p"
    # Hardening flag'lerin hepsi argv içinde, sırası tutarlı
    expected_tail = list(claude_client._HARDENING_FLAGS)
    assert argv[2:] == expected_tail


@pytest.mark.asyncio
async def test_synthesize_includes_strict_mcp_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--strict-mcp-config`` MCP yüklemesini blokluyor (kritik flag)."""
    captured: dict[str, Any] = {}
    _stub_subprocess(monkeypatch, captured=captured, proc=_FakeProc())

    await claude_client.synthesize_with_claude("x")

    assert "--strict-mcp-config" in captured["argv"]


@pytest.mark.asyncio
async def test_synthesize_disables_tools_and_skills(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--tools ""`` + ``--disable-slash-commands`` agentic loop'u kapatır."""
    captured: dict[str, Any] = {}
    _stub_subprocess(monkeypatch, captured=captured, proc=_FakeProc())

    await claude_client.synthesize_with_claude("x")

    argv = captured["argv"]
    assert "--tools" in argv
    # --tools sonrası empty string parametresi (built-in tool'ları kapat)
    tools_idx = argv.index("--tools")
    assert argv[tools_idx + 1] == ""
    assert "--disable-slash-commands" in argv


@pytest.mark.asyncio
async def test_synthesize_passes_prompt_via_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prompt argv yerine stdin'e gider (Windows 32KB sınırı için)."""
    captured: dict[str, Any] = {}
    _stub_subprocess(monkeypatch, captured=captured, proc=_FakeProc())

    await claude_client.synthesize_with_claude("payload-via-stdin")

    assert captured["input"] == "payload-via-stdin"
    assert "payload-via-stdin" not in captured["argv"]


@pytest.mark.asyncio
async def test_synthesize_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError, match="empty"):
        await claude_client.synthesize_with_claude("   ")


@pytest.mark.asyncio
async def test_synthesize_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _stub_subprocess(
        monkeypatch,
        captured=captured,
        proc=_FakeProc(stdout="", stderr="boom", returncode=1),
    )

    with pytest.raises(RuntimeError, match="rc=1"):
        await claude_client.synthesize_with_claude("x")


@pytest.mark.asyncio
async def test_synthesize_raises_when_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(claude_client.shutil, "which", lambda _name: None)

    with pytest.raises(FileNotFoundError, match="not in PATH"):
        await claude_client.synthesize_with_claude("x")


@pytest.mark.asyncio
async def test_custom_timeout_is_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _stub_subprocess(monkeypatch, captured=captured, proc=_FakeProc())

    await claude_client.synthesize_with_claude("x", timeout_seconds=42)

    assert captured["timeout"] == 42

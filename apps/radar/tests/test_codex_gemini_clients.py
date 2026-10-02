"""codex_client + gemini_client tests — subprocess.run mocked."""

from __future__ import annotations

import pytest
from llm.codex_client import review_with_codex
from llm.gemini_client import analyze_with_gemini


def _fake_run_factory(returncode: int, stdout: str, stderr: str = ""):
    """Build a fake subprocess.run that returns the given fields."""
    from subprocess import CompletedProcess

    def fake_run(cmd, **kw):
        return CompletedProcess(args=cmd, returncode=returncode, stdout=stdout, stderr=stderr)

    return fake_run


# ─── codex_client ──────────────────────────────────────────────────────


async def test_review_with_codex_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm.codex_client.shutil.which", lambda _name: "codex")
    monkeypatch.setattr("llm.codex_client.subprocess.run", _fake_run_factory(0, "review text"))
    out = await review_with_codex("review this code")
    assert out == "review text"


async def test_review_with_codex_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty prompt"):
        await review_with_codex("   ")


async def test_review_with_codex_nonzero_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("llm.codex_client.shutil.which", lambda _name: "codex")
    monkeypatch.setattr(
        "llm.codex_client.subprocess.run",
        _fake_run_factory(1, "", "codex died"),
    )
    with pytest.raises(RuntimeError, match="codex CLI failed"):
        await review_with_codex("anything")


async def test_review_with_codex_passes_exec_subcommand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        from subprocess import CompletedProcess

        return CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("llm.codex_client.shutil.which", lambda _name: "codex")
    monkeypatch.setattr("llm.codex_client.subprocess.run", fake_run)
    await review_with_codex("review")
    assert captured["cmd"][0] == "codex"
    assert "exec" in captured["cmd"]
    assert "review" in captured["cmd"]


async def test_review_with_codex_raises_when_codex_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows .cmd resolution regression: shutil.which → None → açıklayıcı hata."""
    monkeypatch.setattr("llm.codex_client.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="codex CLI not in PATH"):
        await review_with_codex("anything")


# ─── gemini_client ─────────────────────────────────────────────────────


async def test_analyze_with_gemini_returns_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm.gemini_client.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr("llm.gemini_client.subprocess.run", _fake_run_factory(0, "gemini said"))
    out = await analyze_with_gemini("analyze this")
    assert out == "gemini said"


async def test_analyze_with_gemini_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty prompt"):
        await analyze_with_gemini("")


async def test_analyze_with_gemini_nonzero_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("llm.gemini_client.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr(
        "llm.gemini_client.subprocess.run",
        _fake_run_factory(2, "", "gemini died"),
    )
    with pytest.raises(RuntimeError, match="gemini CLI failed"):
        await analyze_with_gemini("anything")


async def test_analyze_with_gemini_raises_when_gemini_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows .cmd resolution regression: shutil.which → None → açıklayıcı hata."""
    monkeypatch.setattr("llm.gemini_client.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="gemini CLI not in PATH"):
        await analyze_with_gemini("anything")

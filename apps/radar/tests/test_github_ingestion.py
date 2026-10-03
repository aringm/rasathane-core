"""GitHub ingestion tests — httpx + subprocess mocked, no real network."""

from __future__ import annotations

from pathlib import Path

import pytest
import respx
from httpx import HTTPStatusError, Response
from ingestion.github import (
    GITHUB_API_BASE,
    RepoMetadata,
    estimate_tokens,
    fetch_repo_metadata,
    parse_github_url,
    run_repomix,
)


def test_parse_github_url_canonical() -> None:
    assert parse_github_url("https://github.com/anthropics/anthropic-sdk-python") == (
        "anthropics",
        "anthropic-sdk-python",
    )


def test_parse_github_url_strips_dot_git() -> None:
    assert parse_github_url("https://github.com/owner/repo.git") == ("owner", "repo")


def test_parse_github_url_with_subpath() -> None:
    assert parse_github_url("https://github.com/owner/repo/tree/main/x") == (
        "owner",
        "repo",
    )


def test_parse_github_url_rejects_non_github() -> None:
    with pytest.raises(ValueError, match="Not a GitHub repo URL"):
        parse_github_url("https://gitlab.com/owner/repo")
    with pytest.raises(ValueError):
        parse_github_url("not a url")


def test_estimate_tokens_uses_3_5_chars_ratio() -> None:
    """A 1750-char dump → ~500 tokens (1750/3.5)."""
    assert estimate_tokens(1750) == 500
    assert estimate_tokens("x" * 700) == 200


async def test_fetch_repo_metadata_parses_response() -> None:
    fake_response = {
        "full_name": "anthropics/anthropic-sdk-python",
        "description": "Python SDK for the Anthropic API",
        "language": "Python",
        "stargazers_count": 1234,
        "forks_count": 56,
        "default_branch": "main",
    }
    with respx.mock() as mock:
        mock.get(f"{GITHUB_API_BASE}/repos/anthropics/anthropic-sdk-python").mock(
            return_value=Response(200, json=fake_response)
        )
        metadata = await fetch_repo_metadata("https://github.com/anthropics/anthropic-sdk-python")

    assert isinstance(metadata, RepoMetadata)
    assert metadata.owner == "anthropics"
    assert metadata.name == "anthropic-sdk-python"
    assert metadata.full_name == "anthropics/anthropic-sdk-python"
    assert metadata.primary_language == "Python"
    assert metadata.stars == 1234
    assert metadata.forks == 56
    assert metadata.default_branch == "main"


async def test_fetch_repo_metadata_uses_token_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_token")
    captured: dict = {}

    def capture(request) -> Response:
        captured["headers"] = dict(request.headers)
        return Response(
            200,
            json={
                "full_name": "x/y",
                "stargazers_count": 0,
                "forks_count": 0,
                "default_branch": "main",
            },
        )

    with respx.mock() as mock:
        mock.get(f"{GITHUB_API_BASE}/repos/x/y").mock(side_effect=capture)
        await fetch_repo_metadata("https://github.com/x/y")

    assert captured["headers"]["authorization"] == "Bearer ghp_fake_token"


async def test_fetch_repo_metadata_404_raises() -> None:
    with respx.mock() as mock:
        mock.get(f"{GITHUB_API_BASE}/repos/x/missing").mock(
            return_value=Response(404, json={"message": "Not Found"})
        )
        with pytest.raises(HTTPStatusError):
            await fetch_repo_metadata("https://github.com/x/missing")


async def test_run_repomix_writes_via_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        # Simulate repomix writing output
        cmd_args = list(cmd)
        out_idx = cmd_args.index("--output") + 1
        Path(cmd_args[out_idx]).write_text("repomix dump", encoding="utf-8")
        from subprocess import CompletedProcess

        return CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("ingestion.github.shutil.which", lambda _name: "pnpm")
    monkeypatch.setattr("ingestion.github.subprocess.run", fake_run)
    output_path = tmp_path / "repomix.txt"
    result = await run_repomix(
        "https://github.com/x/y",
        output_path=output_path,
        project_root=tmp_path,
    )
    assert result == output_path
    assert "repomix" in captured["cmd"]
    assert "--remote" in captured["cmd"]
    assert "https://github.com/x/y" in captured["cmd"]


async def test_run_repomix_failure_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(cmd, **kw):
        from subprocess import CompletedProcess

        return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="boom")

    monkeypatch.setattr("ingestion.github.shutil.which", lambda _name: "pnpm")
    monkeypatch.setattr("ingestion.github.subprocess.run", fake_run)
    with pytest.raises(RuntimeError, match="repomix failed"):
        await run_repomix(
            "https://github.com/x/y",
            output_path=tmp_path / "out.txt",
            project_root=tmp_path,
        )


async def test_run_repomix_raises_when_pnpm_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Windows .cmd resolution regression: shutil.which → None → açıklayıcı hata.

    Eski davranış: subprocess.run [WinError 2] atıyordu, kullanıcı "pnpm yok"
    mesajı alamıyordu. Şimdi FileNotFoundError + kurulum linki.
    """
    monkeypatch.setattr("ingestion.github.shutil.which", lambda _name: None)
    with pytest.raises(FileNotFoundError, match="pnpm CLI bulunamadı"):
        await run_repomix(
            "https://github.com/x/y",
            output_path=tmp_path / "out.txt",
            project_root=tmp_path,
        )

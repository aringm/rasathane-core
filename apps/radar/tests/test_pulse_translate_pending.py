"""pulse translate-pending CLI tests."""

from __future__ import annotations

from typer.testing import CliRunner
from worker.cli import app


def test_translate_pending_help_lists_command() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["translate-pending", "--help"])
    assert result.exit_code == 0
    assert "translate-pending" in result.stdout or "translate" in result.stdout.lower()


def test_translate_pending_dispatches_to_pipeline(monkeypatch) -> None:
    """CLI calls translate_short_pending and reports success/fail."""
    captured: dict = {}

    async def fake_pipeline(_session, *, limit: int):
        captured["limit"] = limit
        return 7, 2

    monkeypatch.setattr(
        "worker.cli.translate_short_pending",
        fake_pipeline,
    )

    runner = CliRunner()
    result = runner.invoke(app, ["translate-pending", "--limit", "50"])

    assert result.exit_code == 0
    assert captured["limit"] == 50
    assert "7" in result.stdout
    assert "2" in result.stdout


def test_translate_pending_default_limit(monkeypatch) -> None:
    captured: dict = {}

    async def fake_pipeline(_session, *, limit: int):
        captured["limit"] = limit
        return 0, 0

    monkeypatch.setattr("worker.cli.translate_short_pending", fake_pipeline)

    runner = CliRunner()
    result = runner.invoke(app, ["translate-pending"])

    assert result.exit_code == 0
    assert captured["limit"] == 100

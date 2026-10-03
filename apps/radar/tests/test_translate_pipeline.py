"""translate.py — gemini subprocess wrapped, integration with repo."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from subprocess import CompletedProcess
from typing import Any
from unittest.mock import MagicMock

import pytest
from llm.translate import (
    _build_short_prompt,
    _is_bad_gemini_output,
    _output_mentions_title_topic,
    translate_short_pending,
)


def _fake_run_factory(returncode: int, stdout: str, stderr: str = ""):
    def fake_run(cmd, **kw):
        return CompletedProcess(args=cmd, returncode=returncode, stdout=stdout, stderr=stderr)

    return fake_run


def _make_article(
    *, title: str = "T", summary: str | None = "s", url: str = "https://e.com/x"
) -> Any:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.title = title
    a.summary = summary
    a.url = url
    a.fetched_at = datetime.now(UTC)
    return a


def test_is_bad_gemini_output_detects_english_preamble() -> None:
    assert _is_bad_gemini_output("Okay, I'm ready for your first command.")
    assert _is_bad_gemini_output("I understand my role. I am ready.")
    assert _is_bad_gemini_output("Sure! Let me help you with that.")


def test_is_bad_gemini_output_detects_turkish_preamble() -> None:
    assert _is_bad_gemini_output("Anladım. Türk hukuk asistanı olarak hazırım.")
    assert _is_bad_gemini_output("Hazırım, ilk komutunuzu bekliyorum.")
    assert _is_bad_gemini_output("Tamam, sen bir asistansın diye anladım.")


def test_is_bad_gemini_output_detects_no_content_responses() -> None:
    """RSS summary boşken gemini 'metin sağlayın' meta-cevabı dönerse reject."""
    assert _is_bad_gemini_output("Lütfen özetlememi istediğiniz haber metnini sağlayın.")
    assert _is_bad_gemini_output("Üzgünüm, haber metnine erişimim yok.")
    assert _is_bad_gemini_output(
        "Unfortunately, I cannot summarize the news article without its content."
    )
    assert _is_bad_gemini_output("Haber metni sağlanmadı.")


def test_is_bad_gemini_output_accepts_real_summary() -> None:
    """Gerçek bir Türkçe özet false-positive vermemeli."""
    real = (
        "Anayasa Mahkemesi yeni bir karar yayımladı. Karar, emsal "
        "niteliğinde önemli bir gelişme olarak kabul ediliyor."
    )
    assert not _is_bad_gemini_output(real)


def test_is_bad_gemini_output_accepts_short_legitimate_text() -> None:
    """Kısa ama meşru bir özet kabul edilmeli."""
    short = "Yapay zeka düzenlemesi için yeni bir tasarı meclise sunuldu."
    assert not _is_bad_gemini_output(short)


def test_output_mentions_title_topic_positive() -> None:
    """Output title'dan substantive token içeriyorsa kabul."""
    assert _output_mentions_title_topic(
        "Weaviate 1.31 sürümü çoklu vektör için MUVERA sunar.",
        "Weaviate 1.31 Release",
    )


def test_output_mentions_title_topic_rejects_meta_response() -> None:
    """Output title'dan hiçbir token içermiyorsa reject."""
    assert not _output_mentions_title_topic(
        "The request to get the news article content was denied. Please provide the article text.",
        "Weaviate 1.31 Release",
    )


def test_output_mentions_title_topic_skips_truly_short_title() -> None:
    """Title'da ne 5+ kelime ne de 3+ akronim yoksa check skip."""
    # Sadece kısa lowercase kelimeler — token'a dönüşemez
    assert _output_mentions_title_topic("Anything output here.", "is on a")


def test_output_mentions_title_topic_catches_acronym_in_title() -> None:
    """Title 3+ harfli ALL-CAPS akronim içerirse output o akronimi içermeli."""
    # GAN title token'ı; meta-response içermiyor → reject
    assert not _output_mentions_title_topic(
        "The news article was not provided. Please provide the article text.",
        "From GAN to WGAN",
    )
    # Doğru özet → kabul
    assert _output_mentions_title_topic(
        "Bu makale GAN'dan WGAN'a geçişi anlatıyor.",
        "From GAN to WGAN",
    )


def test_output_mentions_title_topic_handles_turkish_chars() -> None:
    """Türkçe karakterler regex'te yakalanmalı."""
    assert _output_mentions_title_topic(
        "Mahkeme yeni emsal kararı yayımladı.",
        "Mahkeme emsal kararı duyuruldu",
    )


def test_build_short_prompt_includes_all_fields() -> None:
    prompt = _build_short_prompt(title="Başlık", summary="Özet metni", url="https://e.com/a")
    assert "Başlık" in prompt
    assert "Özet metni" in prompt
    assert "https://e.com/a" in prompt


def test_build_short_prompt_handles_none_summary() -> None:
    prompt = _build_short_prompt(title="T", summary=None, url="https://e.com/a")
    assert "T" in prompt
    assert "https://e.com/a" in prompt
    # No literal "None" leakage
    assert "None" not in prompt


async def test_translate_short_pending_zero_pending_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No NULL articles → no gemini calls, success=fail=0."""

    async def fake_find(_session, *, limit: int):
        return []

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)

    success, fail = await translate_short_pending(MagicMock(), limit=10)

    assert success == 0
    assert fail == 0


async def test_translate_short_pending_calls_gemini_per_article(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arts = [_make_article(title=f"T{i}") for i in range(3)]
    saved: dict[uuid.UUID, str] = {}

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(_session, aid, text):
        saved[aid] = text

    # MagicMock as session needs commit/rollback to be awaitable
    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr(
        "llm.translate.subprocess.run",
        _fake_run_factory(0, "Türkçe özet metni"),
    )

    success, fail = await translate_short_pending(session, limit=10)

    assert success == 3
    assert fail == 0
    assert all(v == "Türkçe özet metni" for v in saved.values())


async def test_translate_short_pending_isolates_per_article_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failing gemini call must not stop the rest."""
    arts = [_make_article(title="ok1"), _make_article(title="bad"), _make_article(title="ok2")]
    saved: dict[uuid.UUID, str] = {}
    call_count = {"n": 0}

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(_session, aid, text):
        saved[aid] = text

    # Sadece "claude" CLI'sini mock'la — fallback "gemini" PATH'te yok
    # gibi davransın ki ikinci article'da fallback de fail olsun.
    monkeypatch.setenv("RASATHANE_TRANSLATE_CLI", "claude")
    monkeypatch.setattr(
        "llm.translate.shutil.which",
        lambda name: "claude" if name == "claude" else None,
    )

    def fake_run(cmd, **kw):
        call_count["n"] += 1
        # claude için her makalede 1 çağrı (fallback gemini PATH yok → atlanır)
        if call_count["n"] == 2:
            return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="rate limit")
        return CompletedProcess(args=cmd, returncode=0, stdout="ok summary", stderr="")

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.subprocess.run", fake_run)

    success, fail = await translate_short_pending(session, limit=10)

    assert success == 2
    assert fail == 1
    assert len(saved) == 2  # bad one not saved


async def test_translate_short_pending_calls_gemini_with_prompt_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec verifies CLI flag is --prompt (not -p) for gemini."""
    captured: dict[str, Any] = {}

    async def fake_find(_session, *, limit: int):
        return [_make_article()]

    async def fake_set(*_a, **_kw):
        return None

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    # Default routing claude. Bu test gemini path'ini izole etmek için
    # env override + sadece gemini CLI present yapar.
    monkeypatch.setenv("RASATHANE_TRANSLATE_CLI", "gemini")
    monkeypatch.setattr(
        "llm.translate.shutil.which",
        lambda name: "gemini" if name == "gemini" else None,
    )
    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.subprocess.run", fake_run)

    await translate_short_pending(session, limit=1)

    # Basename "gemini" yeter; Windows'ta absolute path .cmd uzantılı dönebilir
    assert "gemini" in captured["cmd"][0].lower()
    assert "--prompt" in captured["cmd"]


async def test_translate_short_pending_uses_claude_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default primary CLI claude (subscription-friendly, ham veride %100 yield)."""
    captured: dict[str, Any] = {}

    async def fake_find(_session, *, limit: int):
        return [_make_article(title="GPT-5 sürüm notları")]

    async def fake_set(*_a, **_kw):
        return None

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        captured["stdin"] = kw.get("input")
        return CompletedProcess(
            args=cmd, returncode=0, stdout="GPT-5 yeni sürüm notları yayımlandı.", stderr=""
        )

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    # Env override yok → default claude
    monkeypatch.delenv("RASATHANE_TRANSLATE_CLI", raising=False)
    monkeypatch.setattr(
        "llm.translate.shutil.which",
        lambda name: "claude" if name == "claude" else None,
    )
    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.subprocess.run", fake_run)

    success, fail = await translate_short_pending(session, limit=1)

    assert success == 1
    assert fail == 0
    # claude -p stdin pattern (Windows CMD argv 32KB sınırı)
    assert "claude" in captured["cmd"][0].lower()
    assert "-p" in captured["cmd"]
    assert "GPT-5 sürüm notları" in captured["stdin"]  # prompt stdin'den geçti


async def test_translate_short_pending_falls_back_when_primary_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Primary CLI hata verirse fallback denenir; topic-mention guard her ikisinde."""
    saved: dict[uuid.UUID, str] = {}
    call_log: list[str] = []

    async def fake_find(_session, *, limit: int):
        return [_make_article(title="OpenAI API yeniliği")]

    async def fake_set(_session, aid, text):
        saved[aid] = text

    def fake_run(cmd, **kw):
        cli_basename = cmd[0].lower()
        if "claude" in cli_basename:
            call_log.append("claude")
            return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="rate limit")
        if "gemini" in cli_basename:
            call_log.append("gemini")
            return CompletedProcess(
                args=cmd, returncode=0, stdout="OpenAI API'sinde yeni özellik.", stderr=""
            )
        raise AssertionError(f"unexpected cli: {cli_basename}")

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.delenv("RASATHANE_TRANSLATE_CLI", raising=False)
    monkeypatch.setattr(
        "llm.translate.shutil.which",
        lambda name: name,  # her iki CLI da PATH'te
    )
    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.subprocess.run", fake_run)

    success, fail = await translate_short_pending(session, limit=1)

    assert success == 1
    assert fail == 0
    assert call_log == ["claude", "gemini"]  # claude denendi, fail → gemini
    assert "OpenAI" in next(iter(saved.values()))


async def test_translate_short_pending_strips_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    arts = [_make_article()]
    saved: dict[uuid.UUID, str] = {}

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(_session, aid, text):
        saved[aid] = text

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr(
        "llm.translate.subprocess.run",
        _fake_run_factory(0, "  \n  Trimmed text.  \n  "),
    )

    success, _ = await translate_short_pending(session, limit=1)

    assert success == 1
    assert next(iter(saved.values())) == "Trimmed text."


async def test_translate_short_pending_skips_articles_without_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RSS summary boş + title kısaysa gemini'ye gönderme, fail say."""
    arts = [_make_article(title="Short", summary=None)]
    saved: dict[uuid.UUID, str] = {}
    gemini_called = {"n": 0}

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(_session, aid, text):
        saved[aid] = text

    def fake_run(cmd, **kw):
        gemini_called["n"] += 1
        return CompletedProcess(args=cmd, returncode=0, stdout="should not reach", stderr="")

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr("llm.translate.subprocess.run", fake_run)

    success, fail = await translate_short_pending(session, limit=1)

    assert success == 0
    assert fail == 1
    assert saved == {}
    assert gemini_called["n"] == 0  # gemini hiç çağrılmadı


async def test_translate_short_pending_rejects_gemini_preamble(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini "I'm ready" preamble dönerse fail sayılır, DB'ye yazılmaz."""
    arts = [_make_article(title="legit article")]
    saved: dict[uuid.UUID, str] = {}

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(_session, aid, text):
        saved[aid] = text

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr(
        "llm.translate.subprocess.run",
        _fake_run_factory(0, "Okay, I'm ready for your first command."),
    )

    success, fail = await translate_short_pending(session, limit=1)

    assert success == 0
    assert fail == 1
    assert saved == {}  # nothing committed


async def test_translate_short_pending_when_gemini_not_in_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gemini PATH'te yoksa article'lar fail sayılır, exit graceful."""
    arts = [_make_article()]

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(*_a, **_kw):
        return None

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: None)

    success, fail = await translate_short_pending(session, limit=1)

    assert success == 0
    assert fail == 1


async def test_translate_short_pending_handles_lookup_error_distinctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LookupError (concurrent DELETE) sayar fail olarak ama distinct event."""
    arts = [_make_article(title="vanished")]

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set_raises(*_args, **_kwargs):
        raise LookupError(f"article {arts[0].id} not found")

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set_raises)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr(
        "llm.translate.subprocess.run",
        _fake_run_factory(0, "ok"),
    )

    success, fail = await translate_short_pending(session, limit=1)

    assert success == 0
    assert fail == 1


async def test_translate_short_pending_breaks_on_batch_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch deadline aşılırsa loop break — kalan article'lar işlenmez."""
    arts = [_make_article(title=f"T{i}") for i in range(5)]
    saved: dict[uuid.UUID, str] = {}

    async def fake_find(_session, *, limit: int):
        return arts

    async def fake_set(_session, aid, text):
        saved[aid] = text

    # time.monotonic'i 1. iterasyondan sonra deadline'ı aşan değer döndür
    times = iter([0.0, 0.0, 9999.0, 9999.0, 9999.0, 9999.0])

    def fake_monotonic():
        return next(times, 9999.0)

    session = MagicMock()

    async def _async_noop(*args, **kwargs):
        return None

    session.commit = _async_noop
    session.rollback = _async_noop

    monkeypatch.setattr("llm.translate.find_pending_short", fake_find)
    monkeypatch.setattr("llm.translate.set_summary_tr_short", fake_set)
    monkeypatch.setattr("llm.translate.shutil.which", lambda _name: "gemini")
    monkeypatch.setattr(
        "llm.translate.subprocess.run",
        _fake_run_factory(0, "ok"),
    )
    monkeypatch.setattr("llm.translate.time.monotonic", fake_monotonic)

    success, fail = await translate_short_pending(session, limit=10)

    # İlk article işlenir; sonraki iterasyonun başında deadline kontrolü break eder
    assert success == 1
    assert fail == 0
    assert len(saved) == 1

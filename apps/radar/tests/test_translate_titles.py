"""Phase 32-ii: translate_titles_pending + title TR helpers testleri.

LLM subprocess mock'lanır — gerçek claude/gemini çağrısı yok. Heuristic
validation pure-function olduğu için doğrudan test edilir.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from llm.translate import (
    _is_valid_title_output,
    _looks_already_turkish,
)

# ── _looks_already_turkish heuristik ─────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("DeepSeek announces V3 with bigger context", False),
        ("Yargıtay Hukuk Genel Kurulu kararı", True),  # ş, ı
        ("Apple's new AI strategy", False),
        ("Türkiye'de yapay zeka düzenlemesi", True),
        ("OpenAI launches GPT-5", False),
        ("KVKK güncel kararları", True),  # ü, ı
        # "Mixed: TR'de OpenAI haberi" cümlesinde TR-spesifik karakter (ı/ş/ğ/ç/ö/ü) yok;
        # "haberi" Latin "i" — heuristik False döner (LLM çevirmeye gönderir).
        ("Mixed: TR'de OpenAI haberi", False),
        ("Klima çalıştı", True),  # ç, ı
    ],
)
def test_looks_already_turkish_detects_tr_chars(title: str, expected: bool) -> None:
    assert _looks_already_turkish(title) is expected


def test_looks_already_turkish_empty_returns_false() -> None:
    assert _looks_already_turkish("") is False
    assert _looks_already_turkish(None) is False  # type: ignore[arg-type]


# ── _is_valid_title_output sanity check ──────────────────────────────────


def test_is_valid_title_output_clean() -> None:
    assert _is_valid_title_output("DeepSeek V3 yayınlandı", "DeepSeek V3 announced") is True


def test_is_valid_title_output_rejects_empty() -> None:
    assert _is_valid_title_output("", "x") is False
    assert _is_valid_title_output("   ", "x") is False


def test_is_valid_title_output_rejects_too_long() -> None:
    """200+ karakter — LLM monologa girmiş."""
    long_text = "Çok " * 100  # 400 char
    assert _is_valid_title_output(long_text, "x") is False


@pytest.mark.parametrize(
    "preamble",
    [
        "Okay, here is the translation",
        "Sure, the Turkish title is",
        "Anladım, hazırım",
        "Tamam, çeviriyorum",
        "Hello! Let me translate",
    ],
)
def test_is_valid_title_output_rejects_chat_preamble(preamble: str) -> None:
    """Gemini/Claude chat preamble — title değil yorum."""
    assert _is_valid_title_output(preamble + " kelime", "x") is False


@pytest.mark.parametrize(
    "prefix",
    [
        "Çeviri: DeepSeek V3",
        "Türkçe: Apple yapay zeka",
        "TR: Test",
        "Translation: Test",
        "## Test",
        "**Bold**",
    ],
)
def test_is_valid_title_output_rejects_meta_prefixes(prefix: str) -> None:
    """Title sadece çeviri olmalı — prefix ekli olmamalı."""
    assert _is_valid_title_output(prefix, "x") is False


@pytest.mark.parametrize(
    "markdown_text",
    [
        "DeepSeek **V3** yayınlandı",  # bold
        "Apple [yeni AI](url) çıkardı",  # link
        "- DeepSeek V3 release",  # list
        "* DeepSeek bullet",  # list alternatif
        "```code block```",  # code
    ],
)
def test_is_valid_title_output_rejects_markdown(markdown_text: str) -> None:
    """Title saf metin olmalı — markdown markup hayır."""
    assert _is_valid_title_output(markdown_text, "x") is False


# ── translate_titles_pending integration (mock LLM + repo) ───────────────


@pytest.mark.asyncio
async def test_translate_titles_pending_empty_when_no_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """find_pending_title_tr empty → (0, 0) erken return."""
    from llm.translate import translate_titles_pending

    async def fake_find(_session, *, limit=100):
        return []

    monkeypatch.setattr("llm.translate.find_pending_title_tr", fake_find)

    session = MagicMock()
    success, fail = await translate_titles_pending(session, limit=50)
    assert success == 0
    assert fail == 0


@pytest.mark.asyncio
async def test_translate_titles_pending_skips_already_turkish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TR karakterler içeren başlık → LLM bypass, doğrudan metadata.title_tr=title."""
    from llm.translate import translate_titles_pending

    fake_article = MagicMock()
    fake_article.id = "uuid-1"
    fake_article.title = "Türkçe haber başlığı"
    fake_article.source = MagicMock()
    fake_article.source.name = "TR-Source"
    fake_article.source.category = "turkiye_ai"

    async def fake_find(_session, *, limit=100):
        return [fake_article]

    set_calls: list[tuple[Any, str]] = []

    async def fake_set(_session, article_id, title_tr):
        set_calls.append((article_id, title_tr))

    llm_called = False

    async def fake_runner(*args, **kwargs):
        nonlocal llm_called
        llm_called = True
        return "fake LLM output"

    monkeypatch.setattr("llm.translate.find_pending_title_tr", fake_find)
    monkeypatch.setattr("llm.translate.set_article_title_tr", fake_set)
    monkeypatch.setattr("llm.translate._generate_title_tr_with_fallback", fake_runner)

    session = MagicMock()
    session.commit = _make_async_noop()
    session.rollback = _make_async_noop()

    success, _fail = await translate_titles_pending(session, limit=10)

    # Skip path: success=1 (bypass), LLM hiç çağrılmamalı
    assert success == 1
    assert llm_called is False
    assert len(set_calls) == 1
    assert set_calls[0][1] == "Türkçe haber başlığı"  # title aynen geçti


@pytest.mark.asyncio
async def test_translate_titles_pending_skips_too_short_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """8 karakterden kısa başlık → fail (skip)."""
    from llm.translate import translate_titles_pending

    fake_article = MagicMock()
    fake_article.id = "uuid-1"
    fake_article.title = "Hi"  # 2 char
    fake_article.source = MagicMock()
    fake_article.source.name = "X"
    fake_article.source.category = "dunya_ai"

    async def fake_find(_session, *, limit=100):
        return [fake_article]

    monkeypatch.setattr("llm.translate.find_pending_title_tr", fake_find)

    session = MagicMock()
    session.rollback = _make_async_noop()

    success, fail = await translate_titles_pending(session, limit=10)
    assert success == 0
    assert fail == 1


@pytest.mark.asyncio
async def test_translate_titles_pending_llm_success_writes_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """İngilizce başlık → LLM çağrısı → set_article_title_tr ile yaz."""
    from llm.translate import translate_titles_pending

    fake_article = MagicMock()
    fake_article.id = "uuid-1"
    fake_article.title = "DeepSeek announces V3 with bigger context window"
    fake_article.source = MagicMock()
    fake_article.source.name = "DeepSeek Blog"
    fake_article.source.category = "china_ai_models"

    async def fake_find(_session, *, limit=100):
        return [fake_article]

    set_calls: list[tuple[Any, str]] = []

    async def fake_set(_session, article_id, title_tr):
        set_calls.append((article_id, title_tr))

    async def fake_generate(_prompt, _original):
        return "DeepSeek V3'ü daha geniş bağlam penceresi ile duyurdu"

    monkeypatch.setattr("llm.translate.find_pending_title_tr", fake_find)
    monkeypatch.setattr("llm.translate.set_article_title_tr", fake_set)
    monkeypatch.setattr("llm.translate._generate_title_tr_with_fallback", fake_generate)

    session = MagicMock()
    session.commit = _make_async_noop()
    session.rollback = _make_async_noop()

    success, fail = await translate_titles_pending(session, limit=10)

    assert success == 1
    assert fail == 0
    assert set_calls[0][1] == "DeepSeek V3'ü daha geniş bağlam penceresi ile duyurdu"


@pytest.mark.asyncio
async def test_translate_titles_pending_llm_failure_increments_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM exception → fail count artar, success kalmaz."""
    from llm.translate import translate_titles_pending

    fake_article = MagicMock()
    fake_article.id = "uuid-1"
    fake_article.title = "An English title that needs translation"
    fake_article.source = MagicMock()
    fake_article.source.name = "X"
    fake_article.source.category = "dunya_ai"

    async def fake_find(_session, *, limit=100):
        return [fake_article]

    async def fake_generate(_prompt, _original):
        raise RuntimeError("LLM connection failed")

    monkeypatch.setattr("llm.translate.find_pending_title_tr", fake_find)
    monkeypatch.setattr("llm.translate._generate_title_tr_with_fallback", fake_generate)

    session = MagicMock()
    session.commit = _make_async_noop()
    session.rollback = _make_async_noop()

    success, fail = await translate_titles_pending(session, limit=10)
    assert success == 0
    assert fail == 1


def _make_async_noop():  # type: ignore[no-untyped-def]
    """Helper: MagicMock async noop."""

    async def _inner(*args, **kwargs):  # type: ignore[no-untyped-def]
        return None

    return _inner

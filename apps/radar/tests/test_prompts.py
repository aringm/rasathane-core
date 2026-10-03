"""Tests for the Mustache-light prompt template render helper."""

from __future__ import annotations

from pathlib import Path

import pytest
from llm.prompts import load_prompt, render


def test_render_replaces_single_placeholder() -> None:
    out = render("Hello {{name}}", name="dünya")
    assert out == "Hello dünya"


def test_render_replaces_multiple_placeholders() -> None:
    out = render("{{a}} ve {{b}}", a="Türkçe", b="özet")
    assert out == "Türkçe ve özet"


def test_render_leaves_unknown_placeholders_untouched() -> None:
    out = render("{{a}} {{missing}}", a="x")
    assert out == "x {{missing}}"


def test_render_handles_repeated_placeholder() -> None:
    out = render("{{x}}-{{x}}", x="ab")
    assert out == "ab-ab"


def test_render_empty_template_is_empty() -> None:
    assert render("", name="ignored") == ""


def test_render_does_not_recurse_into_substituted_values() -> None:
    """RSS başlığı/url'si {{xxx}} string'i içerebilir — single-pass garantisi."""
    assert render("{{a}}", a="{{b}}") == "{{b}}"
    assert render("{{a}} {{b}}", a="{{b}}", b="x") == "{{b}} x"


def test_load_prompt_reads_packaged_md_file() -> None:
    text = load_prompt("short_summary")
    assert text  # non-empty
    assert "{{title}}" in text
    assert "{{summary}}" in text
    assert "{{url}}" in text


def test_load_prompt_unknown_name_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist_xyz")


# ── Phase 15-ii: brief format kontrat sözleşmesi ─────────────────────


def test_daily_brief_template_requests_markdown_links() -> None:
    """daily_brief.md, claude'a tıklanabilir markdown link talep ediyor olmalı.

    Bu test, ileride bir refactor template'ten link talimatını yanlışlıkla
    kaldırırsa CI'da hemen yakalar — UI link rendering link talimatına bağlı.
    """
    text = load_prompt("daily_brief")
    # Anahtar kelime kombinasyonu: "markdown link" + "tıklanabilir"
    assert "markdown link" in text.lower()
    assert "tıklanabilir" in text
    # Format örneği [başlık](URL) talimatı geçmeli
    assert "[" in text and "](" in text


def test_daily_brief_template_requests_paragraphs() -> None:
    """Phase 15-ii: katı liste yerine paragraf+liste karması istenmeli."""
    text = load_prompt("daily_brief")
    assert "paragraf" in text.lower()

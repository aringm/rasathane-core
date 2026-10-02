"""Phase 32-ii: brief.py podcast helper'ları için unit testler.

_format_date_tr ve _parse_podcast_dialog deterministik, network-free
fonksiyonlar — yüksek hızla broad coverage sağlanabilir.
"""

from __future__ import annotations

import pytest
from rasathane_mcp.core.brief import _format_date_tr, _parse_podcast_dialog

# ── _format_date_tr ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2026-05-17", "17 Mayıs 2026 Pazar"),
        ("2026-01-01", "1 Ocak 2026 Perşembe"),
        ("2026-12-31", "31 Aralık 2026 Perşembe"),
        ("2025-08-30", "30 Ağustos 2025 Cumartesi"),  # Zafer Bayramı
        ("2026-10-29", "29 Ekim 2026 Perşembe"),  # Cumhuriyet Bayramı
    ],
)
def test_format_date_tr_basic_dates(iso: str, expected: str) -> None:
    assert _format_date_tr(iso) == expected


def test_format_date_tr_invalid_returns_iso_unchanged() -> None:
    """Geçersiz format → orijinal string döner (graceful fallback)."""
    assert _format_date_tr("not-a-date") == "not-a-date"
    assert _format_date_tr("2026/05/17") == "2026/05/17"
    assert _format_date_tr("") == ""


def test_format_date_tr_handles_leap_year() -> None:
    """2024 artık yıl, 29 Şubat var."""
    assert _format_date_tr("2024-02-29") == "29 Şubat 2024 Perşembe"


def test_format_date_tr_weekday_correct() -> None:
    """Pazartesi=0 indexing doğru."""
    # 2026-05-18 Pazartesi
    assert "Pazartesi" in _format_date_tr("2026-05-18")
    # 2026-05-24 Pazar
    assert "Pazar" in _format_date_tr("2026-05-24")


# ── _parse_podcast_dialog ────────────────────────────────────────────────


def test_parse_podcast_dialog_clean_json() -> None:
    raw = (
        "[\n"
        '  {"speaker": "Filiz", "text": "Açılış"},\n'
        '  {"speaker": "Mehmet", "text": "Hukuk yorumu"}\n'
        "]"
    )
    dialog = _parse_podcast_dialog(raw)
    assert len(dialog) == 2
    assert dialog[0] == {"speaker": "Filiz", "text": "Açılış"}
    assert dialog[1] == {"speaker": "Mehmet", "text": "Hukuk yorumu"}


def test_parse_podcast_dialog_with_code_fence() -> None:
    """LLM bazen ```json``` wrapper ekler — soyabilmeli."""
    raw = 'İşte podcast diyaloğu:\n```json\n[{"speaker": "Filiz", "text": "Test"}]\n```'
    dialog = _parse_podcast_dialog(raw)
    assert len(dialog) == 1
    assert dialog[0]["text"] == "Test"


def test_parse_podcast_dialog_with_prelude_text() -> None:
    """LLM bazen JSON öncesi ön söz yazar — substring extraction."""
    raw = (
        "Aşağıdaki diyalog hazır:\n\n"
        '[{"speaker": "Filiz", "text": "Açılış"}]\n\n'
        "Umarım faydalı olur."
    )
    dialog = _parse_podcast_dialog(raw)
    assert len(dialog) == 1
    assert dialog[0]["speaker"] == "Filiz"


def test_parse_podcast_dialog_empty_text_filtered() -> None:
    """Boş text satırları atılır."""
    raw = (
        "[\n"
        '  {"speaker": "Filiz", "text": ""},\n'
        '  {"speaker": "Mehmet", "text": "Var"},\n'
        '  {"speaker": "", "text": "Speakeri yok"}\n'
        "]"
    )
    dialog = _parse_podcast_dialog(raw)
    assert len(dialog) == 1
    assert dialog[0]["speaker"] == "Mehmet"


def test_parse_podcast_dialog_invalid_json_returns_empty() -> None:
    assert _parse_podcast_dialog("not json at all") == []
    assert _parse_podcast_dialog("") == []
    assert _parse_podcast_dialog("{}") == []  # dict değil array


def test_parse_podcast_dialog_handles_dict_instead_of_array() -> None:
    """LLM yanlışlıkla dict döndürürse boş liste."""
    raw = '{"speaker": "Filiz", "text": "Tek satır"}'
    assert _parse_podcast_dialog(raw) == []


def test_parse_podcast_dialog_strips_whitespace() -> None:
    """Speaker ve text leading/trailing whitespace temizlenir."""
    raw = '[{"speaker": "  Filiz  ", "text": "  Açılış  "}]'
    dialog = _parse_podcast_dialog(raw)
    assert dialog[0]["speaker"] == "Filiz"
    assert dialog[0]["text"] == "Açılış"


def test_parse_podcast_dialog_non_string_values_coerced() -> None:
    """speaker int olursa str() ile coerce edilir."""
    raw = '[{"speaker": 123, "text": "Test"}]'
    dialog = _parse_podcast_dialog(raw)
    assert dialog[0]["speaker"] == "123"


def test_parse_podcast_dialog_three_speaker_podcast() -> None:
    """Tipik 3-konuşmacı brief podcast yapısı."""
    raw = (
        "[\n"
        '  {"speaker": "Filiz", "text": "Bugün 17 Mayıs 2026 Pazar."},\n'
        '  {"speaker": "Mehmet", "text": "AYM önemli karar verdi."},\n'
        '  {"speaker": "Burak", "text": "AI tarafında DeepSeek release."},\n'
        '  {"speaker": "Filiz", "text": "Mehmet detayları açıkla."},\n'
        '  {"speaker": "Mehmet", "text": "Karar şu yöne işaret ediyor..."}\n'
        "]"
    )
    dialog = _parse_podcast_dialog(raw)
    assert len(dialog) == 5
    speakers = {d["speaker"] for d in dialog}
    assert speakers == {"Filiz", "Mehmet", "Burak"}

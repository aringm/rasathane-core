"""Phase 32-v.4: TR sayı/ordinal/yüzde transliterate testleri."""

from __future__ import annotations

import pytest
from llm.tts import (
    _tr_number_to_words,
    _tr_ordinal_to_words,
    transliterate_numbers_tr,
    transliterate_short_acronyms,
)

# ── _tr_number_to_words ────────────────────────────────────────────────


def test_zero_to_nine() -> None:
    assert _tr_number_to_words(0) == "sıfır"
    assert _tr_number_to_words(1) == "bir"
    assert _tr_number_to_words(9) == "dokuz"


def test_ten_to_nineteen() -> None:
    assert _tr_number_to_words(10) == "on"
    assert _tr_number_to_words(15) == "on beş"
    assert _tr_number_to_words(19) == "on dokuz"


def test_twenty_to_ninety_nine() -> None:
    assert _tr_number_to_words(20) == "yirmi"
    assert _tr_number_to_words(73) == "yetmiş üç"
    assert _tr_number_to_words(99) == "doksan dokuz"


def test_hundreds() -> None:
    assert _tr_number_to_words(100) == "yüz"
    assert _tr_number_to_words(200) == "iki yüz"
    assert _tr_number_to_words(412) == "dört yüz on iki"
    assert _tr_number_to_words(999) == "dokuz yüz doksan dokuz"


def test_thousands() -> None:
    assert _tr_number_to_words(1000) == "bin"
    assert _tr_number_to_words(2000) == "iki bin"
    assert _tr_number_to_words(2026) == "iki bin yirmi altı"
    assert _tr_number_to_words(3500) == "üç bin beş yüz"


def test_millions() -> None:
    assert _tr_number_to_words(1_000_000) == "bir milyon"
    assert _tr_number_to_words(2_500_000) == "iki milyon beş yüz bin"


# ── _tr_ordinal_to_words ──────────────────────────────────────────────


def test_ordinal_simple_vowel_harmony() -> None:
    """Vokal uyumu — son sesli harfe göre ek değişir."""
    assert _tr_ordinal_to_words(1) == "birinci"
    assert _tr_ordinal_to_words(9) == "dokuzuncu"


# ── transliterate_numbers_tr ─────────────────────────────────────────


def test_percent_pattern() -> None:
    out = transliterate_numbers_tr("Büyüme %73 oranında.")
    assert "yüzde yetmiş üç" in out
    assert "%73" not in out


def test_ordinal_pattern_before_capitalized_word() -> None:
    """'9. Hukuk' → 'dokuzuncu Hukuk'."""
    out = transliterate_numbers_tr("Yargıtay 9. Hukuk Dairesi kararı.")
    assert "dokuzuncu Hukuk" in out
    assert "9." not in out


def test_year_pattern() -> None:
    out = transliterate_numbers_tr("2026 yılında karar verildi.")
    assert "iki bin yirmi altı" in out
    assert "2026" not in out


def test_raw_number_pattern() -> None:
    out = transliterate_numbers_tr("Toplam 412 dava var.")
    assert "dört yüz on iki" in out


def test_combined_patterns_sequential() -> None:
    """Yüzde + yıl + ordinal birlikte."""
    out = transliterate_numbers_tr("2026 yılında %73 oranında, 9. Hukuk Dairesi kararı.")
    assert "iki bin yirmi altı" in out
    assert "yüzde yetmiş üç" in out
    assert "dokuzuncu Hukuk" in out


# ── transliterate_short_acronyms entegrasyonu (3-katman) ─────────────


def test_transliterate_applies_number_layer() -> None:
    """transliterate_short_acronyms apply_numbers=True default."""
    # Phase 35-iii: RASATHANE_TR_PRONUNCIATION_PATH kaldırıldı (lab silindi)
    out = transliterate_short_acronyms("Yargıtay 9. Hukuk Dairesi %73 oran.")
    assert "dokuzuncu" in out
    assert "yüzde yetmiş üç" in out


def test_transliterate_skip_numbers_when_disabled() -> None:
    """apply_numbers=False atlar."""
    out = transliterate_short_acronyms(
        "Yargıtay 9. Hukuk %73 oran.",
        apply_numbers=False,
    )
    assert "9. Hukuk" in out
    assert "%73" in out


def test_transliterate_2_layer_order() -> None:
    """Phase 35-iii: TR sayı → EN acronym sırasıyla uygulanır.

    TR pronunciation katmanı (Phase 32-v.2) silindi — ElevenLabs
    multilingual_v2 TR fonetiği native handle eder.
    """
    out = transliterate_short_acronyms("davalı 9. Daire kararında AI kullandı.")
    # TR fix katmanı yok → "davalı" değişmedi
    assert "davalı" in out
    # Sayı/ordinal katmanı çalışır
    assert "dokuzuncu" in out
    # EN acronym katmanı çalışır
    assert "ey-ay" in out

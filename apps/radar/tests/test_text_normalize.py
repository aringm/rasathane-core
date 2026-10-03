"""Phase 15-iii: title normalize heuristic tests.

Türkçe-aware sentence case dönüşümü doğrudan stdlib ile yapılamaz
(``"İSTANBUL".lower()`` Windows locale'a bağlı; "I" → "ı" garanti
değil). ``normalize_title_tr`` özel haritalama kullanır — bu test
seti haritalamayı + heuristic eşiklerini pin'liyor.
"""

from __future__ import annotations

from rasathane_mcp.core.text_normalize import (
    is_mostly_uppercase,
    normalize_title_tr,
    tr_lower,
    tr_upper_first,
)

# ── tr_lower ──────────────────────────────────────────────────────────


def test_tr_lower_handles_turkish_i_dotted_pair() -> None:
    """İ → i ve I → ı (Python stdlib bunu locale'a göre yapar; biz manuel)."""
    assert tr_lower("İSTANBUL") == "istanbul"
    assert tr_lower("AÇIKLAMA") == "açıklama"  # I → ı, diğerleri de TR


def test_tr_lower_passes_through_lowercase() -> None:
    assert tr_lower("istanbul") == "istanbul"


def test_tr_lower_preserves_non_letters() -> None:
    assert tr_lower("AYM 2026/123") == "aym 2026/123"


# ── tr_upper_first ────────────────────────────────────────────────────


def test_tr_upper_first_handles_dotless_i() -> None:
    """ı → I değil İ — ama bizim eşlemede ı → İ değil; check actual map."""
    # ı'nın upper'ı I (dotless), eşlemede _TR_LOWER_TO_UPPER["ı"] = "I"
    assert tr_upper_first("ısrarlı") == "Israrlı"


def test_tr_upper_first_handles_dotted_i() -> None:
    assert tr_upper_first("istanbul") == "İstanbul"


def test_tr_upper_first_empty_returns_empty() -> None:
    assert tr_upper_first("") == ""


# ── is_mostly_uppercase ───────────────────────────────────────────────


def test_is_mostly_uppercase_detects_all_caps() -> None:
    assert is_mostly_uppercase("BAROSU AÇIKLAMA YAPTI")


def test_is_mostly_uppercase_rejects_mixed() -> None:
    assert not is_mostly_uppercase("Anayasa Mahkemesi Kararı")


def test_is_mostly_uppercase_handles_no_letters() -> None:
    assert not is_mostly_uppercase("123 / 2026")


def test_is_mostly_uppercase_threshold_is_80_percent() -> None:
    """4 harften 3'ü upper = %75, threshold %80 → False."""
    assert not is_mostly_uppercase("AbCD")
    # 5 harften 4'ü upper = %80 → True
    assert is_mostly_uppercase("AbCDE")


# ── normalize_title_tr — gerçek senaryolar ────────────────────────────


def test_normalize_all_caps_sentence_case() -> None:
    """Klasik ALL CAPS RSS başlığı → İlk harf büyük, kalan Türkçe küçük.

    Not: input Türkçe-doğru karakterler içerir ("YENİ" değil "YENI" gibi
    ASCII'leştirilmiş başlıklar program tarafından düzeltilemez —
    "I" gerçekten dotless mı yoksa İ mi olduğu ambiguous; heuristic
    "I" → "ı" varsayar, ki saf Türkçe için doğru).
    """
    assert (
        normalize_title_tr("AYM CEZA HUKUKUNDA YENİ KARAR VERDİ")
        == "Aym ceza hukukunda yeni karar verdi"
    )


def test_normalize_handles_ascii_i_with_dotless_assumption() -> None:
    """ASCII "I" gerçek Türkçe-doğru girdide hep dotless 'ı' demektir
    (Türkçe klavyede 'i' tuşlanır, 'I' ayrı bir tuş). RSS'te yanlış
    yazılmış "YENI" → "yenı" çıkar; documentation note olarak böyle
    kabul ediyoruz, kullanıcı feedback'te yakalanırsa açıklama dialog'u."""
    out = normalize_title_tr("AYM CEZA HUKUKUNDA YENI KARAR VERDI")
    # "YENI" → "yenı", "VERDI" → "verdı" (her ikisi de dotless)
    assert "yenı" in out
    assert "verdı" in out


def test_normalize_preserves_short_acronym_titles() -> None:
    """≤ 2 kelime → dokunma (akronim/marka olabilir)."""
    assert normalize_title_tr("KVKK GÜNCELLEME") == "KVKK GÜNCELLEME"
    assert normalize_title_tr("OPENAI") == "OPENAI"


def test_normalize_preserves_mixed_case_title() -> None:
    """Karma case → dokunma."""
    title = "Anayasa Mahkemesi vergi cezalarına dair karar verdi"
    assert normalize_title_tr(title) == title


def test_normalize_handles_none_and_empty() -> None:
    assert normalize_title_tr("") == ""


def test_normalize_strips_outer_whitespace() -> None:
    """Strip ham beklenir (RSS bazen başında/sonunda boşluk verir)."""
    assert normalize_title_tr("  Düzgün başlık burada  ") == "Düzgün başlık burada"


def test_normalize_is_idempotent() -> None:
    """İkinci çağrı aynı sonucu vermeli — UI re-render eşiklerinde önemli."""
    once = normalize_title_tr("YARGITAY 9 HD KARARI YAYIMLADI")
    twice = normalize_title_tr(once)
    assert once == twice


def test_normalize_keeps_numbers_and_punctuation() -> None:
    """Sayılar ve noktalama bozulmamalı."""
    out = normalize_title_tr("AYM 2026/123 SAYILI KARARI YAYIMLADI")
    assert "2026/123" in out
    assert out.startswith("Aym")

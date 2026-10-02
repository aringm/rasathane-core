"""Canonical tag taxonomy — UI filter + brief categorization + social_watch.tags ortak.

Phase 33-ii. Tek source of truth: UI filter pill'leri, Source.category
validation, SocialWatchPerson.tags map'i hepsi buradan beslenir.

Tag color'lar `_base.html` CSS değişkenlerine map'lenir:
    gold/teal/purple/green/terra/cream/red.
"""

from __future__ import annotations

CANONICAL_TAGS: dict[str, dict[str, str | int]] = {
    "tr_hukuk": {"label": "TR Hukuk", "color": "gold", "order": 1},
    "tr_avukat": {"label": "TR Avukat", "color": "gold", "order": 2},
    "tr_ai": {"label": "Türkiye AI", "color": "teal", "order": 3},
    "dunya_ai": {"label": "Dünya AI", "color": "purple", "order": 4},
    "acik_kaynak_ai": {"label": "Açık Kaynak AI", "color": "green", "order": 5},
    "legaltech": {"label": "Legaltech", "color": "terra", "order": 6},
    "resmi_mevzuat": {"label": "Resmi Gazete", "color": "cream", "order": 7},
}

# Legacy alias map — eski source.category değerlerini canonical'a çevir
_ALIASES: dict[str, str] = {
    "tr hukuk": "tr_hukuk",
    "TR Hukuk": "tr_hukuk",
    "dunya ai": "dunya_ai",
    "dunya_AI": "dunya_ai",
    "tr ai": "tr_ai",
    "TR AI": "tr_ai",
    "open_source_ai": "acik_kaynak_ai",
    "rg": "resmi_mevzuat",
    "resmi gazete": "resmi_mevzuat",
}


def normalize(tag: str) -> str | None:
    """Tag string'i canonical key'e map'le. Bilinmiyorsa None döner.

    İlk olarak alias map'i kontrol eder, sonra lowercase/underscore'lu
    direkt match'i. Hiçbiri eşleşmezse None.
    """
    if not tag:
        return None
    if tag in CANONICAL_TAGS:
        return tag
    if tag in _ALIASES:
        return _ALIASES[tag]
    candidate = tag.strip().lower().replace(" ", "_").replace("-", "_")
    if candidate in CANONICAL_TAGS:
        return candidate
    return None


def is_valid(tag: str) -> bool:
    """Canonical key olup olmadığını kontrol eder (normalize etmez)."""
    return tag in CANONICAL_TAGS


def all_tags() -> list[dict[str, str | int]]:
    """Order'a göre sıralı tag list — UI filter pills için."""
    return [
        {"key": key, **meta}
        for key, meta in sorted(CANONICAL_TAGS.items(), key=lambda x: x[1]["order"])
    ]

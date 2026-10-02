"""Phase 32-i: feeds_yaml Literal genişletmesi + canlı data/feeds.yaml parse."""

from __future__ import annotations

from pathlib import Path

import pytest
from ingestion.feeds_yaml import FeedYamlEntry, load_feeds_yaml
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
FEEDS_YAML = REPO_ROOT / "data" / "feeds.yaml"


def test_data_feeds_yaml_parses_with_extended_categories() -> None:
    """data/feeds.yaml — Phase 32-i sonrası — schema validation geçer."""
    parsed = load_feeds_yaml(FEEDS_YAML)
    assert len(parsed.sources) > 60  # 53 baseline + 30+ Phase 32-i


def test_new_category_china_ai_models_accepted() -> None:
    entry = FeedYamlEntry(
        name="Test",
        category="china_ai_models",
        type="rss",
        url="https://example.com/feed",
        metadata={"reliability": "primary"},
    )
    assert entry.category == "china_ai_models"


@pytest.mark.parametrize(
    "category",
    [
        "china_ai_models",
        "east_asia_ai_models",
        "open_weight_models",
        "model_infra",
        "social_watch",
    ],
)
def test_all_new_categories_accepted(category: str) -> None:
    entry = FeedYamlEntry(
        name="X",
        category=category,
        type="rss",
        url="https://example.com/feed",
    )
    assert entry.category == category


def test_legacy_categories_still_accepted() -> None:
    """Geriye uyumluluk — eski 5 kategori değiştirilmedi."""
    for cat in ("turk_hukuku", "dunya_ai", "turkiye_ai", "legaltech", "muhakeme_stack"):
        entry = FeedYamlEntry(name="X", category=cat, type="rss", url="https://example.com/feed")
        assert entry.category == cat


def test_invalid_category_rejected() -> None:
    with pytest.raises(ValidationError):
        FeedYamlEntry(
            name="X",
            category="not_a_real_category",
            type="rss",
            url="https://example.com/feed",
        )


def test_new_type_social_person_accepted() -> None:
    entry = FeedYamlEntry(
        name="@karpathy",
        category="social_watch",
        type="social_person",
        url="https://x.com/karpathy",
    )
    assert entry.type == "social_person"


def test_invalid_type_rejected() -> None:
    with pytest.raises(ValidationError):
        FeedYamlEntry(
            name="X",
            category="dunya_ai",
            type="telegram",  # not in Literal
            url="https://example.com/feed",
        )


def test_data_feeds_no_dead_yaml_entries_explicit_disabled() -> None:
    """Phase 32-i: enabled=false girişler manuel kontrol bekliyor; yine de
    valid schema olmalı.
    """
    parsed = load_feeds_yaml(FEEDS_YAML)
    disabled = [s for s in parsed.sources if not s.enabled]
    # En az birkaç enabled:false giriş Phase 32-i'de eklendi (URL uncertainty)
    assert len(disabled) >= 5
    # Hepsi notes alanı taşımalı — neden disabled açıklanmalı
    for entry in disabled:
        assert entry.metadata.get("notes") or entry.metadata.get("reliability"), (
            f"Disabled entry {entry.name!r} missing notes/reliability"
        )


def test_new_sources_carry_reliability_metadata() -> None:
    """Phase 32-i'de eklenen tüm yeni kategori girişlerinde reliability var."""
    parsed = load_feeds_yaml(FEEDS_YAML)
    new_categories = {
        "china_ai_models",
        "east_asia_ai_models",
        "open_weight_models",
        "model_infra",
    }
    for entry in parsed.sources:
        if entry.category in new_categories:
            assert "reliability" in entry.metadata, (
                f"{entry.name!r} kategorisi {entry.category}, reliability bekleniyor"
            )

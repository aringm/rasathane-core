"""Phase 32-i: source_scoring deterministik formül testleri."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rasathane_mcp.core import source_scoring

# ── score_source: kaynak metadata'sına göre statik skor ──────────────────


def test_score_source_primary_official_global() -> None:
    """primary + official + global region = yüksek skor."""
    metadata = {
        "reliability": "primary",
        "officialness": "official",
        "region": "global",
        "topics": ["open_weight", "reasoning"],
    }
    breakdown = source_scoring.score_source(metadata)
    assert breakdown.score >= 45.0
    assert breakdown.notification_level in ("flash", "digest_candidate")
    assert breakdown.components["reliability"] == 30.0
    assert breakdown.components["officialness"] == 10.0
    assert breakdown.components["topic_strategic"] == 5.0


def test_score_source_rumor_low_score_with_note() -> None:
    """rumor reliability → 0 weight + uyarı notu."""
    metadata = {"reliability": "rumor", "region": "global"}
    breakdown = source_scoring.score_source(metadata)
    assert breakdown.components["reliability"] == 0.0
    assert any("rumor" in n.lower() for n in breakdown.notes)


def test_score_source_legal_topic_boost() -> None:
    """Hukuk topic'i kategorize edilir, yüksek bonus alır."""
    metadata = {
        "reliability": "primary",
        "officialness": "official",
        "region": "turkey",
        "topics": ["legal", "kvkk"],
    }
    breakdown = source_scoring.score_source(metadata)
    assert breakdown.components.get("topic_legal") == 8.0
    assert breakdown.score >= 50.0  # primary + official + turkey + legal


def test_score_source_unknown_reliability_default() -> None:
    """Bilinmeyen reliability → 5.0 nötr katkı."""
    metadata = {"reliability": "made_up_tier"}
    breakdown = source_scoring.score_source(metadata)
    assert breakdown.components["reliability"] == 5.0


# ── score_event: içerik-aware skor + novelty + duplicate ─────────────────


def test_score_event_recent_model_release_high() -> None:
    """Son 2 saat içinde primary kaynaktan model release = flash."""
    now = datetime(2026, 5, 14, 20, 0, tzinfo=UTC)
    metadata = {
        "reliability": "primary",
        "officialness": "official",
        "region": "china",
        "topics": ["open_weight"],
    }
    breakdown = source_scoring.score_event(
        source_metadata=metadata,
        title="Qwen3 release: 235B MoE checkpoint",
        summary="New open-weight model checkpoint with benchmark leaderboard wins",
        published_at=now - timedelta(minutes=30),
        now=now,
    )
    assert breakdown.components["novelty"] == 8.0
    assert breakdown.components["model_relevance"] > 0
    assert breakdown.score >= 60.0


def test_score_event_duplicate_penalty() -> None:
    """Aynı release ikinci kez geldiyse penalty."""
    now = datetime(2026, 5, 14, 20, 0, tzinfo=UTC)
    metadata = {"reliability": "primary", "officialness": "official", "region": "global"}
    base = source_scoring.score_event(
        source_metadata=metadata,
        title="DeepSeek R1 release",
        summary="reasoning model",
        published_at=now - timedelta(hours=3),
        now=now,
        duplicate_count=0,
    )
    dup = source_scoring.score_event(
        source_metadata=metadata,
        title="DeepSeek R1 release",
        summary="reasoning model",
        published_at=now - timedelta(hours=3),
        now=now,
        duplicate_count=2,
    )
    assert dup.score < base.score
    assert dup.components["duplicate_penalty"] == -10.0


def test_score_event_rumor_penalty_extra() -> None:
    """rumor reliability → ek olarak -15 rumor_penalty."""
    now = datetime(2026, 5, 14, tzinfo=UTC)
    metadata = {"reliability": "rumor"}
    breakdown = source_scoring.score_event(
        source_metadata=metadata,
        title="Bir model release söylentisi",
        summary="kaynak gösterilmedi",
        published_at=now - timedelta(hours=1),
        now=now,
    )
    assert breakdown.components["rumor_penalty"] == -15.0
    assert breakdown.notification_level == "watch_only"


def test_score_event_promo_noise_detected() -> None:
    """Reklam dili → -10 promo_noise."""
    now = datetime(2026, 5, 14, tzinfo=UTC)
    metadata = {"reliability": "secondary_verified"}
    breakdown = source_scoring.score_event(
        source_metadata=metadata,
        title="Buy now! Limited time deal — şimdi kayıt fırsatı",
        summary="Save 50%",
        published_at=now,
        now=now,
    )
    assert breakdown.components.get("promo_noise") == -10.0


# ── canonical_event_key + find_duplicates ────────────────────────────────


def test_canonical_event_key_normalizes_punctuation_and_case() -> None:
    """Aynı başlık farklı punctuation/case → aynı key."""
    k1 = source_scoring.canonical_event_key(
        title="DeepSeek-R1 Release!", url="https://X.com/a?ref=1"
    )
    k2 = source_scoring.canonical_event_key(title="deepseek r1 release", url="https://x.com/a")
    assert k1 == k2


def test_find_duplicates_exact_and_fuzzy() -> None:
    """Title token-set Jaccard ile fuzzy duplicate yakala."""
    events = [
        {
            "title": "Qwen3 Coder release with bigger context",
            "url": "https://github.com/QwenLM/Qwen3-Coder/releases/tag/v1",
        },
        {
            "title": "Qwen3 Coder release bigger context window",
            "url": "https://huggingface.co/Qwen/Qwen3-Coder",
        },
        {"title": "Unrelated post about Postgres tuning", "url": "https://example.com/pg"},
        {
            "title": "DeepSeek R1 launches",
            "url": "https://github.com/deepseek-ai/DeepSeek-R1/releases/tag/r1",
        },
        {
            "title": "DeepSeek R1 launches",
            "url": "https://github.com/deepseek-ai/DeepSeek-R1/releases/tag/r1",
        },
    ]
    groups = source_scoring.find_duplicates(events, title_similarity_threshold=0.7)
    assert len(groups) >= 1
    # Exact duplicates must be grouped:
    exact_pair = next((g for g in groups if 3 in g and 4 in g), None)
    assert exact_pair is not None


def test_find_duplicates_empty_input() -> None:
    """Boş input → boş liste, hata yok."""
    assert source_scoring.find_duplicates([]) == []


def test_classify_level_thresholds() -> None:
    """Skor → notification level eşikleri net."""
    assert source_scoring._classify_level(80.0) == "flash"
    assert source_scoring._classify_level(60.0) == "digest_candidate"
    assert source_scoring._classify_level(30.0) == "archive_only"
    assert source_scoring._classify_level(10.0) == "watch_only"

"""Kaynak ve olay (event) skorlama + duplicate detection.

Phase 32-i: Kaynak yönetim ajanı, raporlar üretirken hangi olayın hangi
seviyede önemli olduğunu açıklayabilir bir skor üzerinden değerlendirir.

Scoring formülü (açıklanabilir + deterministik):

    score = (
        source_weight             # primary > secondary > community > rumor
        + officialness_bonus      # official > semi_official > community
        + topic_match_bonus       # ilgili topic etiketi → +bonus
        + novelty_bonus           # son N saat içinde mi
        + model_relevance         # model release/benchmark signal
        + legal_relevance         # hukuk/regülasyon signal
        + ai_relevance            # AI/ML araştırma signal
        + muhakeme_stack_bonus    # muhakeme.ai stack uyumlu
        + region_priority         # bölge önceliği (china/global)
        + engagement_signal       # community sinyal (RT/like proxy)
        - duplicate_penalty       # aynı release birden fazla kaynaktan geldi
        - rumor_penalty           # rumor reliability → -bonus
        - promo_noise             # spam/reklam içerik
    )

Skor 0-100 normalize. Bildirim seviyeleri:
    - score >= 75 → flash       (kritik release/API değişikliği)
    - score >= 50 → digest      (günlük/haftalık özete girer)
    - score >= 25 → archive     (sadece arşivlenir)
    - score <  25 → watch_only  (doğrulanmamış sinyal, eylem yok)
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

NotificationLevel = Literal["flash", "digest_candidate", "archive_only", "watch_only"]


# ── Source weight tabloları ──────────────────────────────────────────────


_RELIABILITY_WEIGHTS: dict[str, float] = {
    "primary": 30.0,
    "secondary_verified": 20.0,
    "community_signal": 10.0,
    "rumor": 0.0,
}

_OFFICIALNESS_BONUS: dict[str, float] = {
    "official": 10.0,
    "semi_official": 5.0,
    "community": 0.0,
}

_REGION_PRIORITY: dict[str, float] = {
    "global": 6.0,
    "china": 6.0,
    "turkey": 8.0,
    "japan": 4.0,
    "korea": 4.0,
    "singapore": 3.0,
    "india": 3.0,
}


# ── Açıklanabilir skor breakdown ─────────────────────────────────────────


@dataclass(frozen=True)
class ScoreBreakdown:
    """Bir kaynak veya olay için skor + bileşenler.

    ``components`` her bir bonus/penalty bileşeninin katkısını tutar; UI
    veya rapor "neden bu skor?" sorusunu cevaplayabilir.
    """

    score: float
    notification_level: NotificationLevel
    components: dict[str, float]
    notes: list[str]


def _classify_level(score: float) -> NotificationLevel:
    if score >= 75.0:
        return "flash"
    if score >= 50.0:
        return "digest_candidate"
    if score >= 25.0:
        return "archive_only"
    return "watch_only"


def score_source(metadata: dict[str, Any]) -> ScoreBreakdown:
    """Bir kaynak metadata'sından statik (içerik-bağımsız) skor üret.

    Bu skor "kaynak ne kadar takip-değer" sorusunu yanıtlar; bir olay
    (article) skorunu hesaplarken bu kaynak-skoru bir bileşendir.
    """
    components: dict[str, float] = {}
    notes: list[str] = []

    reliability = (metadata.get("reliability") or "").lower()
    components["reliability"] = _RELIABILITY_WEIGHTS.get(reliability, 5.0)
    if reliability == "rumor":
        notes.append("rumor güvenilirlik — otomatik yüksek-öncelikli rapora alınmaz")

    officialness = (metadata.get("officialness") or "").lower()
    components["officialness"] = _OFFICIALNESS_BONUS.get(officialness, 0.0)

    region = (metadata.get("region") or "").lower()
    components["region_priority"] = _REGION_PRIORITY.get(region, 0.0)

    priority = metadata.get("priority")
    if isinstance(priority, (int, float)):
        # 1-10 → 0-10 ek bonus
        components["priority"] = max(0.0, min(10.0, float(priority)))

    topics = metadata.get("topics") or []
    if isinstance(topics, list):
        if any(t in topics for t in ("open_weight", "reasoning", "agentic")):
            components["topic_strategic"] = 5.0
        if any(t in topics for t in ("legal", "kvkk", "veri_koruma", "hukuk")):
            components["topic_legal"] = 8.0

    score = sum(components.values())
    return ScoreBreakdown(
        score=round(score, 2),
        notification_level=_classify_level(score),
        components=components,
        notes=notes,
    )


def score_event(
    *,
    source_metadata: dict[str, Any],
    title: str,
    summary: str | None,
    published_at: datetime | None,
    now: datetime | None = None,
    duplicate_count: int = 0,
) -> ScoreBreakdown:
    """Bir olay (article) için içerik-aware skor.

    ``duplicate_count`` aynı release/release-event'in N kaynaktan kaç defa
    geldiğini gösterir. 0 = ilk gelen; 1+ = duplicate penalty uygulanır
    (1 başka kaynaktan da geldi → release güvenilirliği artar AMA aynı
    sinyali iki kez raporlama).
    """
    now = now or datetime.now(UTC)
    source_score = score_source(source_metadata)
    components = dict(source_score.components)
    notes = list(source_score.notes)

    text = f"{title} {summary or ''}".lower()

    # Novelty — published son 24h içinde ise bonus
    if published_at is not None:
        published_utc = published_at if published_at.tzinfo else published_at.replace(tzinfo=UTC)
        age = now - published_utc
        if age < timedelta(hours=2):
            components["novelty"] = 8.0
        elif age < timedelta(hours=24):
            components["novelty"] = 5.0
        elif age < timedelta(days=7):
            components["novelty"] = 2.0
        else:
            components["novelty"] = 0.0

    # Topic relevance — basit anahtar kelime tabanlı, deterministik
    components["model_relevance"] = _model_relevance(text)
    components["legal_relevance"] = _legal_relevance(text)
    components["ai_relevance"] = _ai_relevance(text)
    components["muhakeme_stack_bonus"] = _stack_relevance(text)

    # Dedup penalty — 2. kez geldiyse -5, 3+ kez geldiyse -10
    if duplicate_count == 1:
        components["duplicate_penalty"] = -5.0
        notes.append(
            "Aynı sinyal başka bir kaynaktan da geldi → güvenilirlik teyidi, ama dedup penalty"
        )
    elif duplicate_count >= 2:
        components["duplicate_penalty"] = -10.0
        notes.append(f"Aynı sinyal {duplicate_count + 1} farklı kaynaktan geldi → ağır dedup")

    # Rumor penalty zaten reliability bileşeninde düşük, ek penalty:
    if (source_metadata.get("reliability") or "").lower() == "rumor":
        components["rumor_penalty"] = -15.0

    # Promo / spam noise
    if _looks_promotional(text):
        components["promo_noise"] = -10.0
        notes.append("Reklam/promosyon dili tespit edildi")

    score = sum(components.values())
    score = max(0.0, min(100.0, score))
    return ScoreBreakdown(
        score=round(score, 2),
        notification_level=_classify_level(score),
        components=components,
        notes=notes,
    )


# ── Topic relevance tetikleyicileri ──────────────────────────────────────


_MODEL_KEYWORDS = (
    "release",
    "launching",
    "introduces",
    "model card",
    "checkpoint",
    "open-weight",
    "open source",
    "benchmark",
    "leaderboard",
    "gpt-",
    "claude ",
    "gemini",
    "qwen",
    "deepseek",
    "mistral",
    "llama",
    "kimi",
    "minimax",
    "hunyuan",
    "exaone",
    "sealion",
    "sarvam",
    "training run",
    "context length",
    "tokens",
)

_LEGAL_KEYWORDS = (
    "yargıtay",
    "danıştay",
    "anayasa mahkemesi",
    "aym",
    "mevzuat",
    "regülasyon",
    "regulation",
    "compliance",
    "kvkk",
    "gdpr",
    "ai act",
    "executive order",
    "court",
    "judge",
    "ruling",
    "lawsuit",
    "dava",
    "kanun",
    "yönetmelik",
    "telif",
    "iktibas",
    "fikir ve sanat",
)

_AI_KEYWORDS = (
    "transformer",
    "attention",
    "fine-tuning",
    "rlhf",
    "rl",
    "dpo",
    "agentic",
    "agent",
    "tool use",
    "function calling",
    "mcp",
    "rag",
    "embedding",
    "vector",
    "inference",
    "serving",
    "vllm",
    "quantization",
    "moe",
    "mixture of experts",
    "reasoning",
)

_STACK_KEYWORDS = (
    "python",
    "postgres",
    "pgvector",
    "fastapi",
    "uv",
    "ollama",
    "claude code",
    "claude desktop",
    "mcp server",
    "structlog",
    "alembic",
    "sqlalchemy",
    "asyncpg",
)


def _kw_score(text: str, keywords: Iterable[str], max_pts: float, per_hit: float) -> float:
    hits = sum(1 for kw in keywords if kw in text)
    return min(max_pts, hits * per_hit)


def _model_relevance(text: str) -> float:
    return _kw_score(text, _MODEL_KEYWORDS, max_pts=12.0, per_hit=2.5)


def _legal_relevance(text: str) -> float:
    return _kw_score(text, _LEGAL_KEYWORDS, max_pts=14.0, per_hit=3.0)


def _ai_relevance(text: str) -> float:
    return _kw_score(text, _AI_KEYWORDS, max_pts=8.0, per_hit=1.5)


def _stack_relevance(text: str) -> float:
    return _kw_score(text, _STACK_KEYWORDS, max_pts=4.0, per_hit=1.0)


_PROMO_PATTERNS = (
    "buy now",
    "limited time",
    "deal",
    "discount",
    "free trial",
    "save 50",
    "şimdi kayıt",
    "indirimle",
    "kazanma fırsatı",
    "fırsat",
)


def _looks_promotional(text: str) -> bool:
    return sum(1 for pat in _PROMO_PATTERNS if pat in text) >= 2


# ── Duplicate detection ──────────────────────────────────────────────────


_URL_HASH_TRIM_RE = re.compile(r"[#?].*$")
_PUNCT_RE = re.compile(r"[\W_]+")


def canonical_event_key(*, title: str, url: str | None = None) -> str:
    """Bir olay için "kanonik" key — aynı release/event farklı kaynaklardan
    gelse bile aynı key'i üretir.

    Strateji: title normalize + URL host+path (query/fragment çıkar).
    """
    norm_title = _PUNCT_RE.sub(" ", title.lower()).strip()
    norm_title = re.sub(r"\s+", " ", norm_title)
    parts = [norm_title]
    if url:
        cleaned = _URL_HASH_TRIM_RE.sub("", url.strip().lower())
        # Common URL shorteners and CDN variants normalize to canonical
        cleaned = re.sub(r"^https?://(www\.)?", "", cleaned)
        parts.append(cleaned)
    raw = " | ".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def find_duplicates(
    events: Sequence[dict[str, Any]],
    *,
    title_similarity_threshold: float = 0.85,
) -> list[list[int]]:
    """Olay listesinde duplicate grupları döndür.

    ``events`` her biri ``{"title": ..., "url": ...}`` şeklinde. Return:
    duplicate grupların indeksleri (her grup en az 2 eleman içerir).

    İki kademe:
      1. Exact: kanonik key eşleşmesi.
      2. Fuzzy: normalize edilmiş title'lar Jaccard >= threshold.
    """
    by_key: dict[str, list[int]] = {}
    for i, e in enumerate(events):
        key = canonical_event_key(title=e.get("title", ""), url=e.get("url"))
        by_key.setdefault(key, []).append(i)

    exact_groups = [idxs for idxs in by_key.values() if len(idxs) >= 2]
    if title_similarity_threshold >= 1.0:
        return exact_groups

    # Fuzzy pass: title token-set Jaccard
    norm_titles = [set(_PUNCT_RE.sub(" ", e.get("title", "").lower()).split()) for e in events]
    fuzzy_groups: list[list[int]] = []
    assigned: set[int] = {i for grp in exact_groups for i in grp}
    for i in range(len(events)):
        if i in assigned:
            continue
        group = [i]
        for j in range(i + 1, len(events)):
            if j in assigned:
                continue
            inter = norm_titles[i] & norm_titles[j]
            union = norm_titles[i] | norm_titles[j]
            if not union:
                continue
            jaccard = len(inter) / len(union)
            if jaccard >= title_similarity_threshold:
                group.append(j)
                assigned.add(j)
        if len(group) >= 2:
            assigned.add(i)
            fuzzy_groups.append(group)

    return exact_groups + fuzzy_groups

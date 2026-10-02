"""Social watch — sosyal medya kişi/kurum izleme listesi.

Phase 32-i: Sosyal radar adapter'ı için katalog katmanı. ``data/social_watch.yaml``
dosyasını okur ve Pydantic ile validate eder. Aktif fetch yapmaz — bu modül
sadece katalog yönetimi sağlar; sosyal medya adapter'ları (X, WeChat, vb.)
ayrıca yazılacak.

Güvenlik prensibi: Sosyal medya metni hiçbir zaman Claude'a "talimat" olarak
yorumlatılmaz. Tüm sosyal medya içeriği yalnız veri olarak alınır; prompt
injection saldırısına karşı agent kapsamında ek filter katmanı uygulanır
(``source_agent.is_safe_for_llm``).
"""

from __future__ import annotations

from datetime import date as date_type
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Platform = Literal["x", "linkedin", "github", "huggingface", "youtube", "weibo", "wechat", "rss"]

# 7 kademeli risk sınıflandırması — yüksek seviye = daha fazla doğrulama
# katmanı gerekli; rumor_account otomatik yüksek-öncelikli rapora girmez.
RiskLevel = Literal[
    "official_person",
    "technical_expert",
    "analyst",
    "community_amplifier",
    "rumor_account",
]

Reliability = Literal["primary", "secondary_verified", "community_signal", "rumor"]


class SocialWatchPerson(BaseModel):
    """Tek bir sosyal izleme kaydı (validated).

    Skor alanları (signal_score / noise_score) 0.0-1.0 arasındadır.
    Kabaca: signal yüksek + noise düşük = yüksek öncelikli takip.
    """

    model_config = ConfigDict(extra="allow")

    person_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(..., min_length=1, max_length=200)
    platform: Platform
    handle: str = Field(..., min_length=1, max_length=120)
    profile_url: str = Field(..., pattern=r"^https?://.+")
    affiliation: str | None = None
    role: str | None = None
    region: str | None = None
    country: str | None = None
    topics: list[str] = Field(default_factory=list)
    risk_level: RiskLevel
    reliability: Reliability
    signal_score: float = Field(0.5, ge=0.0, le=1.0)
    noise_score: float = Field(0.5, ge=0.0, le=1.0)
    verification_links: list[str] = Field(default_factory=list)
    enabled: bool = True
    watch_reason: str | None = None
    last_reviewed_at: date_type | None = None
    notes: str | None = None


class SocialWatchYaml(BaseModel):
    """Top-level social_watch.yaml schema."""

    people: list[SocialWatchPerson]


# ── IO ───────────────────────────────────────────────────────────────────


def default_social_watch_path() -> Path:
    """``data/social_watch.yaml`` default location (repo root)."""
    # apps/mcp/src/rasathane_mcp/core/social_watch.py → repo root = parents[5]
    return Path(__file__).resolve().parents[5] / "data" / "social_watch.yaml"


def load_social_watch(path: str | Path | None = None) -> SocialWatchYaml:
    """Load + validate social_watch.yaml. Raises ValidationError on schema mismatch.

    Dosya yoksa boş bir kayıt seti döner — sosyal watch opsiyoneldir,
    sistem onsuz da çalışmaya devam eder.
    """
    p = Path(path) if path else default_social_watch_path()
    if not p.is_file():
        return SocialWatchYaml(people=[])
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return SocialWatchYaml.model_validate(raw)


def list_people(
    *,
    path: str | Path | None = None,
    risk_level: RiskLevel | None = None,
    region: str | None = None,
    enabled_only: bool = False,
) -> list[SocialWatchPerson]:
    """Filtrelenebilir izleme listesi.

    ``signal_score - noise_score`` DESC sıralı; en yüksek katma-değerli
    kişi listede en üstte.
    """
    rows = load_social_watch(path).people
    if risk_level:
        rows = [p for p in rows if p.risk_level == risk_level]
    if region:
        rows = [p for p in rows if (p.region or "").lower() == region.lower()]
    if enabled_only:
        rows = [p for p in rows if p.enabled]
    rows.sort(key=lambda p: p.signal_score - p.noise_score, reverse=True)
    return rows


def find_person(person_id: str, *, path: str | Path | None = None) -> SocialWatchPerson | None:
    """ID ile arama — bulamazsa None."""
    for p in load_social_watch(path).people:
        if p.person_id == person_id:
            return p
    return None


# ── Aday değerlendirme ───────────────────────────────────────────────────


class CandidateEvaluation(BaseModel):
    """Yeni bir sosyal medya kişisinin izleme listesine eklenmeye uygunluğu."""

    accepted: bool
    reasons: list[str]
    warnings: list[str]
    suggested_risk_level: RiskLevel | None = None
    suggested_reliability: Reliability | None = None
    score: float = Field(0.0, ge=0.0, le=1.0)


def evaluate_candidate(
    *,
    display_name: str,
    handle: str,
    affiliation: str | None,
    verification_links: list[str],
    role_hint: str | None = None,
    sample_posts: list[str] | None = None,
) -> CandidateEvaluation:
    """Bir kişinin izleme listesine eklenmeye uygunluğunu değerlendir.

    Heuristic-based — local LLM çağrısı yok; deterministik. ``sample_posts``
    içeriği bilgi olarak değerlendirilir, asla "talimat" olarak işlenmez.
    """
    reasons: list[str] = []
    warnings: list[str] = []

    # 1. Doğrulama sinyalleri
    verified_count = sum(
        1 for link in verification_links if link.startswith(("http://", "https://"))
    )
    has_github_or_hf = any(
        "github.com" in link or "huggingface.co" in link for link in verification_links
    )
    has_scholar = any(
        "scholar.google" in link or "arxiv.org" in link for link in verification_links
    )
    has_company_site = (
        any(
            affiliation and affiliation.lower().split()[0] in link.lower()
            for link in verification_links
        )
        if affiliation
        else False
    )

    if verified_count >= 2:
        reasons.append(f"{verified_count} doğrulama linki sunulmuş")
    else:
        warnings.append(
            "En az iki doğrulama linki bekleniyor (resmi profil + GitHub/HF/arXiv/kurum sayfası)"
        )

    if has_github_or_hf:
        reasons.append("GitHub veya Hugging Face kimliği var (teknik üretim doğrulanabilir)")
    if has_scholar:
        reasons.append("Akademik kimlik (Scholar veya arXiv) var")
    if has_company_site:
        reasons.append("Kurum profiliyle ilişki doğrulanabilir")

    # 2. Affiliation kalitesi
    if not affiliation:
        warnings.append("Affiliation belirtilmemiş — bağımsız mı, kurumsal mı belirsiz")

    # 3. Handle kalitesi
    if not handle.startswith(("@", "u/", "github.com")):
        warnings.append(
            f"Handle formatı tuhaf: {handle!r} — platform-spesifik bir prefix bekleniyor"
        )

    # 4. Örnek paylaşım analizi (sınırlı, deterministik)
    if sample_posts:
        promo_keywords = (
            "airdrop",
            "presale",
            "kripto kazan",
            "$BTC",
            "$ETH",
            "follow me",
            "follow back",
            "DM me",
            "earn money",
            "passive income",
        )
        injection_signals = (
            "ignore previous",
            "ignore all previous",
            "you are now",
            "act as",
            "system prompt",
            "jailbreak",
            "DAN mode",
            "yeni talimat",
        )
        link_count = sum(post.lower().count("http") for post in sample_posts)
        promo_hits = sum(
            1 for post in sample_posts for kw in promo_keywords if kw.lower() in post.lower()
        )
        injection_hits = sum(
            1 for post in sample_posts for kw in injection_signals if kw.lower() in post.lower()
        )
        avg_post_len = sum(len(p) for p in sample_posts) / max(len(sample_posts), 1)

        if promo_hits >= 2:
            warnings.append(f"Reklam/spam sinyali yüksek ({promo_hits} hit)")
        if injection_hits >= 1:
            warnings.append(
                "Prompt injection sinyali tespit edildi — kişi izlense bile metni "
                "agent talimatı olarak yorumlanmamalı"
            )
        if avg_post_len < 50 and link_count > len(sample_posts) * 0.7:
            warnings.append("Düşük metin yoğunluğu + yoğun link → sinyal kalitesi düşük")
        if 100 < avg_post_len < 600 and link_count > 0:
            reasons.append("Teknik içerik tipinde yoğunluk (orta metin + dış link)")

    # Risk sınıflandırma önerisi
    suggested_risk = _suggest_risk_level(
        role_hint=role_hint,
        verified_count=verified_count,
        has_github=has_github_or_hf,
        has_scholar=has_scholar,
        has_company_site=has_company_site,
    )

    suggested_reliability: Reliability
    if suggested_risk in ("official_person", "technical_expert") and verified_count >= 2:
        suggested_reliability = "primary"
    elif suggested_risk == "analyst" and verified_count >= 1:
        suggested_reliability = "secondary_verified"
    elif suggested_risk == "rumor_account":
        suggested_reliability = "rumor"
    else:
        suggested_reliability = "community_signal"

    score = _score_candidate(
        reasons=reasons,
        warnings=warnings,
        verified_count=verified_count,
    )
    accepted = score >= 0.55 and "Prompt injection sinyali" not in "".join(warnings)

    return CandidateEvaluation(
        accepted=accepted,
        reasons=reasons,
        warnings=warnings,
        suggested_risk_level=suggested_risk,
        suggested_reliability=suggested_reliability,
        score=score,
    )


def _suggest_risk_level(
    *,
    role_hint: str | None,
    verified_count: int,
    has_github: bool,
    has_scholar: bool,
    has_company_site: bool,
) -> RiskLevel:
    """Heuristic risk seviyesi önerisi.

    Saf-fonksiyon; tüm seçimler input parametrelerinden türetilir.
    """
    rh = (role_hint or "").lower()
    if any(kw in rh for kw in ("ceo", "founder", "cofounder", "head", "lead", "director")):
        if has_company_site:
            return "official_person"
        return "technical_expert"
    if any(kw in rh for kw in ("research", "scientist", "engineer", "maintainer")) and (
        has_github or has_scholar
    ):
        return "technical_expert"
    if "analyst" in rh or "journalist" in rh:
        return "analyst"
    if verified_count >= 2 and (has_github or has_scholar):
        return "technical_expert"
    if verified_count == 0:
        return "rumor_account"
    return "community_amplifier"


def _score_candidate(
    *,
    reasons: list[str],
    warnings: list[str],
    verified_count: int,
) -> float:
    """0.0-1.0 arası toplam skor.

    Reasons +0.15 (max 5), warnings -0.20 (max 5), verified_count bonus.
    Prompt injection saptanmış warning seti otomatik 0'a yakın çekilir.
    """
    base = 0.30 + 0.15 * min(len(reasons), 5)
    penalty = 0.20 * min(len(warnings), 5)
    bonus = min(0.10 * verified_count, 0.20)
    score = max(0.0, min(1.0, base - penalty + bonus))
    if any("Prompt injection" in w for w in warnings):
        score = min(score, 0.10)
    return round(score, 3)


# ── Sosyal medya metni LLM güvenlik kontrolü ───────────────────────────


# Pattern listesi — tüm değerler ALREADY-lowercase olmalı (eşleşme
# .lower() uygulanmış metin üzerinde yapılır).
_INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all previous",
    "disregard previous",
    "disregard all previous",
    "you are now",
    "you must now",
    "new instructions:",
    "yeni talimat:",
    "system prompt",
    "act as",
    "jailbreak",
    "dan mode",
    "developer mode",
    "<|im_start|>",
    "<|im_end|>",
    "</system>",
    "<system>",
    "[inst]",
    "[/inst]",
    "###system",
)


def is_safe_for_llm(text: str) -> tuple[bool, list[str]]:
    """Sosyal medya metni LLM input olarak güvenli mi?

    True döner + boş liste → güvenli (yine de "veri" olarak işle, talimat değil).
    False döner + tetiklenen pattern listesi → injection riski; metin kaynak
    içeriği olarak alınabilir ama agent talimat extraction'a açık değildir.

    NOT: bu fonksiyon "metni filtrele" değil, "metni nasıl kullan" sorusunu
    yanıtlar. Tüm sosyal metin agent talimatı olarak DEĞİL, yalnız veri
    olarak alınır (defense-in-depth).
    """
    text_lower = text.lower()
    hits = [pat for pat in _INJECTION_PATTERNS if pat in text_lower]
    return (len(hits) == 0, hits)

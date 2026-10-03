"""``feeds.yaml`` loader and DB sync.

The yaml file is the source of truth for the ``Source`` table. Running
``pulse sync-feeds`` upserts: existing rows update, new rows insert.
Removed rows are NOT deleted automatically — they are soft-disabled via
``enabled: false`` in the yaml when desired (so historical articles
remain linked).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from store.repository import upsert_sources_from_dicts

# Active ingester types (must align with ``INGESTER_REGISTRY``).
# ``rss`` covers regular feeds + Medium per-author feeds (Atom/RSS).
# ``arxiv`` uses the Atom API for richer metadata. ``reddit`` JSON.
# Phase 12-iv: ``youtube_channel`` yt-dlp flat-playlist (RSS endpoint
# 2026-05-07'de YouTube tarafında 404 verince eklendi).
# Phase 32-i: ``social_person`` katalog-only tip — sosyal medya kişi izleme
# girişleri için. INGESTER_REGISTRY'de yok; ``sync_one_source`` çağrılırsa
# "no ingester for type 'social_person'" hatasıyla graceful fail eder.
# Adapter zemini hazırlanırken katalog tarafı yaşamaya devam eder.
SourceType = Literal[
    "rss",
    "arxiv",
    "reddit",
    "youtube_channel",
    "social_person",
    # Phase 32-iv: Resmî Gazete günlük yayın (HTML index parser).
    "resmi_gazete",
]
SourceCategory = Literal[
    "turk_hukuku",
    "dunya_ai",
    "turkiye_ai",
    "legaltech",
    "muhakeme_stack",
    # Phase 32-i: AI model ekosistemi + sosyal radar genişletmesi
    "china_ai_models",
    "east_asia_ai_models",
    "open_weight_models",
    "model_infra",
    "social_watch",
    # Phase 32-iv: Türk resmî mevzuat ana kaynağı.
    "resmi_mevzuat",
]

# Kaynak güvenilirlik seviyeleri. Skorlama ve raporlama için kullanılır.
# ``primary``        : resmi şirket/lab blogu, docs, GitHub org, HF org, arXiv
# ``secondary_verified``: güvenilir teknoloji yayını veya araştırma bülteni
# ``community_signal``: Reddit, X, Discord, forum, bağımsız araştırmacı
# ``rumor``          : doğrulanmamış sosyal medya iddiası (otomatik raporlamaz)
Reliability = Literal["primary", "secondary_verified", "community_signal", "rumor"]


class FeedYamlEntry(BaseModel):
    """One entry in feeds.yaml (validated).

    ``metadata`` opaque dict olarak kalır (geriye uyumluluk için), fakat
    aşağıdaki anahtarlar zincir genelinde tanınır:

    Kaynak meta:
      - ``lang``             : ISO dil kodu, örn. "tr", "en", "zh"
      - ``region``           : "global" | "china" | "japan" | "korea" | ...
      - ``country``          : ISO ülke kodu veya açık adı
      - ``platform``         : kaynak platformu ("blog", "github", "huggingface", ...)
      - ``officialness``     : "official" | "semi_official" | "community"
      - ``reliability``      : ``Reliability`` Literal değerleri
      - ``priority``         : 1-10 (yüksek = daha öncelikli takip)
      - ``topics``           : list[str] — ilgi konuları
      - ``model_families``   : list[str] — model aileleri (yalnız model kaynakları)
      - ``company_or_lab``   : "Anthropic", "Qwen / Alibaba" gibi
      - ``feed_url``         : kanonik feed URL (url'den farklıysa)
      - ``api_type``         : "rss_atom", "rest", "graphql", "webhook"
      - ``notes``            : kısa serbest metin
      - ``added_by``         : "user" → dashboard'dan eklendi
    """

    name: str
    category: SourceCategory
    type: SourceType
    url: str
    enabled: bool = True
    fetch_interval_minutes: int = Field(default=60, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FeedYaml(BaseModel):
    """Top-level feeds.yaml schema."""

    sources: list[FeedYamlEntry]


def load_feeds_yaml(path: str | Path) -> FeedYaml:
    """Load + validate feeds.yaml. Raises on schema errors."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FeedYaml.model_validate(raw)


async def sync_feeds_yaml_to_db(
    session: AsyncSession,
    path: str | Path,
) -> tuple[int, int]:
    """Read feeds.yaml + upsert into ``Source`` table.

    Returns ``(inserted_count, updated_count)``. Caller must commit.
    """
    feeds = load_feeds_yaml(path)
    return await upsert_sources_from_dicts(
        session,
        [e.model_dump() for e in feeds.sources],
    )

"""YouTube channel ingester (yt-dlp flat-playlist mode).

Phase 12-iv: YouTube'un eski RSS endpoint'i
(``feeds/videos.xml?channel_id=UC...``) 2026-05-07 itibariyle 404 dönüyor.
Bu ingester yt-dlp'nin ``--flat-playlist`` modunu kullanarak channel
sayfasından video listesini çeker — heavy fetch (transcript/whisper)
yok, sadece liste.

feeds.yaml'da ``type: youtube_channel`` ile kaydedilen source'lar bu
ingester'a yönlendirilir. URL formatı serbest:
  - https://www.youtube.com/@AndrejKarpathy
  - https://www.youtube.com/@AndrejKarpathy/videos
  - https://www.youtube.com/channel/UCXUPKJO5MZQN11PqgIvyuvQ
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from ingestion.base import BaseIngester, IngestedArticle
from ingestion.youtube import list_channel_videos

log = structlog.get_logger()

# Default per-channel limit. yt-dlp flat-playlist 50 video listeler
# (channel-page'in default), ama brief 24sa odaklı, bu yüzden ~25 yeter.
DEFAULT_MAX_VIDEOS = 25
SUMMARY_MAX_WORDS = 200  # FSEK iktibas sınırı (Article model docstring)


def _parse_yt_upload_date(date_str: str | None) -> datetime | None:
    """yt-dlp'nin ``YYYYMMDD`` string'ini UTC datetime'a çevir."""
    if not date_str or len(date_str) != 8:
        return None
    try:
        return datetime(
            int(date_str[:4]),
            int(date_str[4:6]),
            int(date_str[6:8]),
            tzinfo=UTC,
        )
    except (ValueError, TypeError):
        return None


def _cap_words(text: str | None, n: int) -> str | None:
    if not text:
        return None
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n]) + "…"


class YoutubeChannelIngester(BaseIngester):
    """List recent videos from a channel; return as IngestedArticle batch.

    Heavy fetch (transcript via whisper) HARİÇ — sadece title + URL +
    description. Brief generation tarafı bu metadata'yı kullanır.
    Phase 12-iv deep-dive ile transcript on-demand çekilebilir.
    """

    type_name = "youtube_channel"

    async def fetch(
        self,
        source_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestedArticle]:
        max_count = (metadata or {}).get("max_videos") or DEFAULT_MAX_VIDEOS
        try:
            videos = await list_channel_videos(source_url, max_count=int(max_count))
        except Exception as e:
            raise RuntimeError(f"yt-dlp channel list failed: {e}") from e

        articles: list[IngestedArticle] = []
        for v in videos:
            url = v["url"]
            title = (v.get("title") or "(başlıksız)")[:1024]
            summary = _cap_words(v.get("description"), SUMMARY_MAX_WORDS)
            published_at = _parse_yt_upload_date(v.get("upload_date"))
            articles.append(
                IngestedArticle(
                    url=url,
                    url_hash=IngestedArticle.hash_url(url),
                    title=title,
                    summary=summary,
                    author=None,  # uploader bilgisi flat-playlist'te tutarsız
                    published_at=published_at,
                    metadata={
                        "channel_url": source_url,
                        "video_id": v["id"],
                        "duration_seconds": v.get("duration"),
                        "kind": "youtube_video",
                        **(metadata or {}),
                    },
                )
            )

        log.info("yt_channel.fetched", channel=source_url, count=len(articles))
        return articles

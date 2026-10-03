"""Phase 32-iv: Resmî Gazete günlük yayın ingester'ı.

Resmî Gazete (resmigazete.gov.tr) günlük index sayfalarını HTTP üzerinden
çekip her yönetmelik/tebliğ/karar girdisini ``IngestedArticle`` olarak
döner. URL pattern: ``/eskiler/YYYY/MM/YYYYMMDD.htm``. Sayfa
``windows-1254`` (Latin-5) encoded, frontpage HTML — manuel decode +
basit parser.

Mimari prensip: Rasathane LLM çağırmaz. Bu ingester yalnız index'i
parse eder; her maddenin tam metin özetini Claude (brief generation'da)
veya kullanıcı (kütüphane analizinde) üretir.

Source meta:
  - ``url``  = base ``https://www.resmigazete.gov.tr`` (günlük URL
              ingester içinde tarihten üretilir)
  - ``metadata.days_back`` (opsiyonel, int, default 1): kaç gün geriye
                             ek olarak çek (1 = sadece bugün, 3 = bugün
                             + 2 önceki gün). Hafta sonu yayın olmazsa
                             404 → skip + warning.

Per-makale meta (article.metadata):
  - ``gazete_date``  : "YYYY-MM-DD" (string, indeksleme için)
  - ``gazete_no``    : "33257" gibi resmî sayı
  - ``bolum``        : "YÖNETMELİKLER" / "TEBLİĞLER" / "İLÂN BÖLÜMÜ" / vb.
  - ``item_index``   : sayfa içi sıra (1-based)
  - ``source``       : "resmi_gazete"
"""

from __future__ import annotations

import html
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import structlog

from ingestion.base import BaseIngester, IngestedArticle

log = structlog.get_logger()

USER_AGENT = "Rasathane/1.0 (https://github.com/aringm/rasathane; nemezis@tutamail.com)"
HTTP_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
BASE_URL = "https://www.resmigazete.gov.tr"

# Index sayfasındaki başlık tag'lerini yakala — <u>YÖNETMELİKLER</u>,
# <u>TEBLİĞLER</u>, <u>YÜRÜTME VE İDARE BÖLÜMÜ</u>. Resmî Gazete'nin
# FrontPage HTML'i <u> içine <font>, <b>, <span> sarar; ``[^<]+?`` ile
# içeriği yakalayamayız → ``.+?`` + DOTALL + clean_text() tag sıyır.
_SECTION_RE = re.compile(r"<u[^>]*>(?P<name>.+?)</u>", re.IGNORECASE | re.DOTALL)

# Madde linkleri: <a href="20260518-1.htm"...>başlık</a>. Resmî Gazete'nin
# eski FrontPage HTML'i atribut sırasını değiştiriyor, tolerant parse.
# Tebliğler genelde PDF (20260518-8.pdf), Yönetmelikler HTM (20260518-1.htm) —
# her ikisi de kabul edilir; dedupe filename basename üzerinden.
_ITEM_LINK_RE = re.compile(
    r'<a\s+href="(?P<href>\d{8}-\d+\.(?:htm|pdf))"[^>]*>(?P<text>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)

# Sayfa başlığında resmî gazete sayısı: "33257 Sayılı Resmî Gazete"
_GAZETE_NO_RE = re.compile(r"(\d{4,6})\s*Say[ıi]l[ıi]\s+Resm", re.IGNORECASE)

# HTML temizleme: tüm tag'leri sil, entity decode, whitespace daralt.
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_NBSP_DOUBLE_DASH_RE = re.compile(r"^[\s \-—–]+")


def _decode_page(body: bytes) -> str:
    """Resmî Gazete sayfaları windows-1254 (Latin-5); UTF-8 nadiren.

    Önce meta charset'i kontrol et — değilse default windows-1254.
    Decode hatasında 'replace' ile düşmemek için 'ignore' kullan
    (bilinmeyen karakter < %0.1, başlık parsing'i bozmaz).
    """
    head = body[:1024].lower()
    if b"utf-8" in head:
        return body.decode("utf-8", errors="ignore")
    return body.decode("windows-1254", errors="ignore")


def _clean_text(text: str) -> str:
    """HTML tag/entity sil, leading dash/nbsp sıyır, whitespace daralt."""
    no_tags = _HTML_TAG_RE.sub(" ", text)
    decoded = html.unescape(no_tags)
    collapsed = _WHITESPACE_RE.sub(" ", decoded).strip()
    # Resmî Gazete maddelerin başında "––" veya "—" tireleri var, sıyır.
    return _NBSP_DOUBLE_DASH_RE.sub("", collapsed).strip()


def _parse_index_page(
    body: bytes,
    *,
    gazete_date: date,
    base_url: str = BASE_URL,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Index HTML → (gazete_no, items).

    Items: list of dicts ``{href, title, bolum, item_index}``.
    Section tracking: linear walk; bir ``<u>SECTION</u>`` görünce
    sonraki linkler o section'a ait (next section başlayana kadar).
    """
    text = _decode_page(body)
    no_match = _GAZETE_NO_RE.search(text)
    gazete_no = no_match.group(1) if no_match else None

    # Position-aware: tüm match'leri sırayla tara, section ve link'i sıraya göre düzenle.
    events: list[tuple[int, str, str]] = []  # (pos, kind, value)
    for m in _SECTION_RE.finditer(text):
        events.append((m.start(), "section", m.group("name").strip()))
    for m in _ITEM_LINK_RE.finditer(text):
        events.append((m.start(), "link", f"{m.group('href')}|||{m.group('text')}"))
    events.sort(key=lambda x: x[0])

    items: list[dict[str, Any]] = []
    current_bolum: str | None = None
    item_index = 0
    seen_hrefs: set[str] = set()  # aynı href birden çok yerde geçebilir, dedupe
    yyyymmdd = gazete_date.strftime("%Y%m%d")
    yyyy = gazete_date.strftime("%Y")
    mm = gazete_date.strftime("%m")
    for _pos, kind, value in events:
        if kind == "section":
            current_bolum = _clean_text(value) or current_bolum
            continue
        href, link_text = value.split("|||", 1)
        # Filter: yalnız bu güne ait href (cross-day navigation linklerini çıkar).
        # ``20260518-N.htm`` veya ``20260518-N.pdf`` (Tebliğler genelde PDF).
        if not href.startswith(yyyymmdd + "-"):
            continue
        # Dedupe key: lowercase filename — aynı maddenin .htm ve .pdf
        # versiyonu varsa bir kez sayılsın (genelde olmaz ama defansif).
        dedupe_key = href.lower()
        if dedupe_key in seen_hrefs:
            continue
        seen_hrefs.add(dedupe_key)
        title = _clean_text(link_text)
        if not title or len(title) < 3:
            continue
        item_index += 1
        absolute = f"{base_url}/eskiler/{yyyy}/{mm}/{href}"
        items.append(
            {
                "href": absolute,
                "title": title,
                "bolum": current_bolum or "Bilinmeyen Bölüm",
                "item_index": item_index,
            }
        )

    return gazete_no, items


def _build_daily_url(target: date, *, base_url: str = BASE_URL) -> str:
    """``date`` → tam URL: ``{base}/eskiler/YYYY/MM/YYYYMMDD.htm``."""
    return f"{base_url}/eskiler/{target:%Y/%m/%Y%m%d}.htm"


class ResmiGazeteIngester(BaseIngester):
    """Resmî Gazete günlük yayın ingester (HTML index parser).

    Source URL ``base`` rolü oynar — ingester günlük URL'i tarihten
    üretir. ``metadata.days_back`` ile geriye doğru N gün de dahil
    edilir (hafta sonu / resmî tatil 404 → skip + warning, fatal değil).

    Output: günlük her madde ayrı ``IngestedArticle``. Body fetch YOK
    (lazy — kütüphane analizinde gerekirse alınır). ``summary=None``
    bilinçli: Claude brief generation'ı başlığı + metadata'yı kullanarak
    özet üretir; rasathane LLM çağırmaz prensibi.
    """

    type_name = "resmi_gazete"

    async def fetch(
        self,
        source_url: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[IngestedArticle]:
        meta = metadata or {}
        days_back = max(1, min(int(meta.get("days_back", 1)), 7))
        # source_url base override izni — testlerde / mirror için.
        base_url = source_url.rstrip("/") if source_url else BASE_URL

        targets = [date.today() - timedelta(days=i) for i in range(days_back)]
        articles: list[IngestedArticle] = []

        async with httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        ) as client:
            for target in targets:
                url = _build_daily_url(target, base_url=base_url)
                try:
                    response = await client.get(url)
                except httpx.HTTPError as e:
                    log.warning(
                        "resmi_gazete.fetch_failed",
                        url=url,
                        date=target.isoformat(),
                        err=str(e)[:200],
                    )
                    continue
                if response.status_code == 404:
                    # Pazar veya bayramda yayın olmaz; sessiz skip.
                    log.info("resmi_gazete.no_issue", date=target.isoformat(), url=url)
                    continue
                if response.status_code >= 400:
                    log.warning(
                        "resmi_gazete.http_error",
                        url=url,
                        date=target.isoformat(),
                        status=response.status_code,
                    )
                    continue

                gazete_no, items = _parse_index_page(
                    response.content,
                    gazete_date=target,
                    base_url=base_url,
                )
                if not items:
                    log.warning(
                        "resmi_gazete.empty_index",
                        date=target.isoformat(),
                        url=url,
                    )
                    continue

                published = datetime(target.year, target.month, target.day, tzinfo=UTC)
                for item in items:
                    common_meta: dict[str, Any] = {
                        "gazete_date": target.isoformat(),
                        "gazete_no": gazete_no,
                        "bolum": item["bolum"],
                        "item_index": item["item_index"],
                        "source": "resmi_gazete",
                    }
                    # Source-level meta (lang, focus vb.) korunur, ama bizim
                    # üretilen alanlar override eder (priority).
                    merged = {**meta, **common_meta} if meta else common_meta

                    article_url = item["href"]
                    title_capped = item["title"][:1024]
                    articles.append(
                        IngestedArticle(
                            url=article_url,
                            url_hash=IngestedArticle.hash_url(article_url),
                            title=title_capped,
                            summary=None,  # lazy — brief generation üretir
                            author=None,
                            published_at=published,
                            metadata=merged,
                        )
                    )

                log.info(
                    "resmi_gazete.fetched",
                    date=target.isoformat(),
                    gazete_no=gazete_no,
                    count=len(items),
                )

        log.info(
            "resmi_gazete.total_fetched",
            days_back=days_back,
            articles=len(articles),
        )
        return articles

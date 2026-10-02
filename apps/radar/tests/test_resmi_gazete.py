"""Phase 32-iv: Resmî Gazete ingester testleri.

Network mocked (respx); gerçek resmigazete.gov.tr çağrısı yapılmaz.
Sample HTML fixture'ı gerçek 2026-05-18 sayfasının kısaltılmış halidir
(windows-1254 encoding, FrontPage HTML).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import pytest
import respx
from freezegun import freeze_time
from ingestion.resmi_gazete import (
    BASE_URL,
    ResmiGazeteIngester,
    _build_daily_url,
    _decode_page,
    _parse_index_page,
)

# Gerçek Resmî Gazete (18 Mayıs 2026) index sayfasının kısaltılmış,
# windows-1254 encoded bytes karşılığı. Test edilen: bölüm tespiti,
# madde linki regex, gazete sayısı çıkarımı, dedupe.
_SAMPLE_INDEX_HTML = """<html>
<head>
<meta http-equiv="Content-Language" content="tr">
<meta http-equiv="Content-Type" content="text/html; charset=windows-1254">
<title>T.C. Resmî Gazete</title>
</head>
<body>
<table>
<tr><td><b>18 Mayıs 2026 Tarihli ve 33257 Sayılı Resmî Gazete</b></td></tr>
</table>

<p><b><u><font face="Arial" color="#000080">YÜRÜTME VE İDARE BÖLÜMÜ</font></u></b></p>
<p><b><u><font face="Arial">YÖNETMELİKLER</font></u></b></p>

<p><a href="20260518-1.htm">––  İzmir Bakırçay Üniversitesi Dil ve Konuşma Bozuklukları Eğitim Uygulama ve Araştırma Merkezi Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik</a></p>
<p><a href="20260518-2.htm">––  İzmir Bakırçay Üniversitesi Fizyoterapi ve Rehabilitasyon Uygulama ve Araştırma Merkezi Yönetmeliğinde Değişiklik Yapılmasına Dair Yönetmelik</a></p>
<p><a href="20260518-3.htm">––  Sivas Cumhuriyet Üniversitesi Lisansüstü Eğitim ve Öğretim Yönetmeliği</a></p>

<p><b><u><font face="Arial">TEBLİĞLER</font></u></b></p>

<p><a href="20260518-4.htm">––  2026 Yılı Nisan Ayına Ait Dahilde İşleme İzin Belgelerinin (D1) Listesi</a></p>
<p><a href="20260518-5.htm">––  2026 Yılı Nisan Ayına Ait Yurt İçi Satış ve Teslim Belgelerinin (D3) Listesi</a></p>

<p><b><u><font face="Arial">İLÂN BÖLÜMÜ</font></u></b></p>

<p><a href="20260518-6.htm">– T.C. Merkez Bankasınca Belirlenen Devlet İç Borçlanma Senetlerinin Günlük Değerleri</a></p>

<!-- Önceki gün navigasyonu - filter etmeli -->
<p><a href="20260517-1.htm">Dünkü Resmî Gazete</a></p>

<!-- Aynı href tekrar - dedupe -->
<p><a href="20260518-1.htm">İzmir Bakırçay (link 2)</a></p>
</body>
</html>
"""


# ── Helper unit tests ────────────────────────────────────────────────────


def test_decode_page_handles_windows_1254() -> None:
    """Windows-1254 (Latin-5) decode — Türkçe karakterler kaybolmasın."""
    text = "İzmir Bakırçay Üniversitesi şöhret"
    body = text.encode("windows-1254")
    decoded = _decode_page(body)
    assert "İzmir" in decoded
    assert "Bakırçay" in decoded
    assert "şöhret" in decoded


def test_decode_page_prefers_utf8_when_advertised() -> None:
    """Sayfa <meta charset=utf-8> diyorsa UTF-8 kullan."""
    text = "Test başlık özel"
    body = b'<meta charset="utf-8">' + text.encode("utf-8")
    decoded = _decode_page(body)
    assert "başlık" in decoded


def test_build_daily_url_formats_correctly() -> None:
    """``date(2026, 5, 18)`` → ``/eskiler/2026/05/20260518.htm``."""
    url = _build_daily_url(date(2026, 5, 18))
    assert url == f"{BASE_URL}/eskiler/2026/05/20260518.htm"


def test_build_daily_url_zero_pads_month_and_day() -> None:
    """``date(2026, 1, 5)`` → ``/eskiler/2026/01/20260105.htm``."""
    url = _build_daily_url(date(2026, 1, 5))
    assert "/2026/01/20260105.htm" in url


# ── _parse_index_page coverage ───────────────────────────────────────────


def test_parse_index_extracts_gazete_no() -> None:
    """Sayfa başlığından "33257 Sayılı Resmî Gazete" → "33257"."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    gazete_no, _items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    assert gazete_no == "33257"


def test_parse_index_extracts_six_distinct_items() -> None:
    """Sample 6 madde + 1 önceki gün nav + 1 duplicate — 6 unique kalmalı."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    _no, items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    assert len(items) == 6
    # Önceki gün href filter test
    assert all("20260518-" in item["href"] for item in items)


def test_parse_index_associates_items_with_sections() -> None:
    """Linear walk: <u>SECTION</u> sonrası gelen linkler o section'a ait."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    _no, items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    by_href = {item["href"].split("/")[-1]: item for item in items}
    # YÖNETMELİKLER section (linkler 1-3)
    assert "YÖNETMELİKLER" in by_href["20260518-1.htm"]["bolum"]
    assert "YÖNETMELİKLER" in by_href["20260518-3.htm"]["bolum"]
    # TEBLİĞLER section (linkler 4-5)
    assert "TEBLİĞ" in by_href["20260518-4.htm"]["bolum"].upper()
    assert "TEBLİĞ" in by_href["20260518-5.htm"]["bolum"].upper()
    # İLÂN BÖLÜMÜ (link 6)
    assert "İLÂN" in by_href["20260518-6.htm"]["bolum"]


def test_parse_index_strips_leading_dashes_from_title() -> None:
    """``"––  İzmir Bakırçay..."`` → ``"İzmir Bakırçay..."``."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    _no, items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    first = items[0]["title"]
    assert not first.startswith("–")
    assert not first.startswith("-")
    assert first.startswith("İzmir")


def test_parse_index_builds_absolute_urls() -> None:
    """href relative → absolute ``{base}/eskiler/YYYY/MM/href``."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    _no, items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    for item in items:
        assert item["href"].startswith(f"{BASE_URL}/eskiler/2026/05/")


def test_parse_index_dedupes_repeated_hrefs() -> None:
    """Sample HTML aynı 20260518-1.htm'i iki kez içerir; tek kayıt dön."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    _no, items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    hrefs = [item["href"] for item in items]
    assert len(hrefs) == len(set(hrefs))


def test_parse_index_assigns_sequential_item_index() -> None:
    """``item_index`` 1-based sıralı (sayfa içi yer sırası)."""
    body = _SAMPLE_INDEX_HTML.encode("windows-1254")
    _no, items = _parse_index_page(body, gazete_date=date(2026, 5, 18))
    indexes = [item["item_index"] for item in items]
    assert indexes == list(range(1, len(items) + 1))


def test_parse_index_empty_body_returns_no_items() -> None:
    _no, items = _parse_index_page(b"<html></html>", gazete_date=date(2026, 5, 18))
    assert items == []


# ── ResmiGazeteIngester.fetch (respx mock) ──────────────────────────────


@pytest.mark.asyncio
@freeze_time("2026-05-18")
async def test_fetch_single_day_returns_articles_with_metadata() -> None:
    """1 günlük fetch: sample sayfayı serve et, IngestedArticle DTO'lar dön."""
    target = date(2026, 5, 18)
    daily_url = _build_daily_url(target)
    with respx.mock(assert_all_called=True) as router:
        router.get(daily_url).respond(
            200,
            content=_SAMPLE_INDEX_HTML.encode("windows-1254"),
            headers={"Content-Type": "text/html; charset=windows-1254"},
        )
        ingester = ResmiGazeteIngester()
        articles = await ingester.fetch(BASE_URL, metadata={"days_back": 1})

    assert len(articles) == 6
    first = articles[0]
    assert first.url.startswith(f"{BASE_URL}/eskiler/2026/05/")
    assert first.title.startswith("İzmir Bakırçay")
    assert first.summary is None  # lazy; brief üretiminde doldurur
    assert first.published_at is not None
    assert first.published_at.year == 2026
    assert first.published_at.month == 5
    assert first.published_at.day == 18
    assert first.metadata["gazete_no"] == "33257"
    assert first.metadata["gazete_date"] == "2026-05-18"
    assert "YÖNETMELİKLER" in first.metadata["bolum"]
    assert first.metadata["item_index"] == 1
    assert first.metadata["source"] == "resmi_gazete"


@pytest.mark.asyncio
@freeze_time("2026-05-19")  # Pazartesi — bugün için 404 (rest gün), dün 18 (sample)
async def test_fetch_404_skips_silently() -> None:
    """Hafta sonu/bayram 404 → skip + log, fatal değil. Sonraki gün dene.

    Sample HTML 2026-05-18 tarihli; bugünü 2026-05-19 alıp 404 ver,
    yesterday=2026-05-18 sample'la eşleşsin.
    """
    today = date(2026, 5, 19)
    yesterday = today - timedelta(days=1)  # 2026-05-18
    with respx.mock(assert_all_called=True) as router:
        router.get(_build_daily_url(today)).respond(404)
        router.get(_build_daily_url(yesterday)).respond(
            200,
            content=_SAMPLE_INDEX_HTML.encode("windows-1254"),
        )
        ingester = ResmiGazeteIngester()
        articles = await ingester.fetch(BASE_URL, metadata={"days_back": 2})

    assert len(articles) == 6
    assert articles[0].metadata["gazete_date"] == yesterday.isoformat()


@pytest.mark.asyncio
@freeze_time("2026-05-18")
async def test_fetch_clamps_days_back_upper_to_seven() -> None:
    """days_back > 7 → 7 (DDoS koruması). 7 gün hepsi 404 → 7 fetch denenir."""
    target = date(2026, 5, 18)
    with respx.mock(assert_all_called=True) as router:
        for i in range(7):
            router.get(_build_daily_url(target - timedelta(days=i))).respond(404)
        ingester = ResmiGazeteIngester()
        articles = await ingester.fetch(BASE_URL, metadata={"days_back": 999})
        assert articles == []


@pytest.mark.asyncio
@freeze_time("2026-05-18")
async def test_fetch_clamps_days_back_lower_to_one() -> None:
    """days_back < 1 → 1 (tek fetch, bugünün maddeleri)."""
    target = date(2026, 5, 18)
    with respx.mock(assert_all_called=True) as router:
        router.get(_build_daily_url(target)).respond(
            200,
            content=_SAMPLE_INDEX_HTML.encode("windows-1254"),
        )
        ingester = ResmiGazeteIngester()
        articles = await ingester.fetch(BASE_URL, metadata={"days_back": 0})
        assert len(articles) == 6


@pytest.mark.asyncio
@freeze_time("2026-05-18")
async def test_fetch_http_error_logged_not_raised() -> None:
    """Network hatası → log + boş dön (cron'u patlatma)."""
    target = date(2026, 5, 18)
    with respx.mock(assert_all_called=True) as router:
        router.get(_build_daily_url(target)).mock(side_effect=httpx.ConnectError("network down"))
        ingester = ResmiGazeteIngester()
        articles = await ingester.fetch(BASE_URL, metadata={"days_back": 1})
        assert articles == []


@pytest.mark.asyncio
@freeze_time("2026-05-18")
async def test_fetch_empty_index_logged_not_raised() -> None:
    """Sayfa 200 ama parse hiçbir madde bulamadıysa boş dön + log warn."""
    target = date(2026, 5, 18)
    with respx.mock(assert_all_called=True) as router:
        router.get(_build_daily_url(target)).respond(
            200,
            content=b"<html><body><p>nothing here</p></body></html>",
        )
        ingester = ResmiGazeteIngester()
        articles = await ingester.fetch(BASE_URL, metadata={"days_back": 1})
        assert articles == []


@pytest.mark.asyncio
@freeze_time("2026-05-18")
async def test_fetch_preserves_source_metadata_with_override() -> None:
    """Source-level meta (lang, focus) korunur; ingester field'ları override."""
    target = date(2026, 5, 18)
    with respx.mock(assert_all_called=True) as router:
        router.get(_build_daily_url(target)).respond(
            200,
            content=_SAMPLE_INDEX_HTML.encode("windows-1254"),
        )
        ingester = ResmiGazeteIngester()
        source_meta: dict[str, Any] = {
            "lang": "tr",
            "focus": "test_focus",
            "days_back": 1,
            # Üretilen 'source' field'ı override etmeli (resmi_gazete priority)
            "source": "should_be_overridden",
        }
        articles = await ingester.fetch(BASE_URL, metadata=source_meta)
    assert articles[0].metadata["lang"] == "tr"
    assert articles[0].metadata["focus"] == "test_focus"
    assert articles[0].metadata["source"] == "resmi_gazete"

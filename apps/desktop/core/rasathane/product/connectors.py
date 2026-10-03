from __future__ import annotations

import html
import os
import re
import threading
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from rasathane.product.web import safe_get, safe_json_request, validate_public_url

_session_lock = threading.Lock()
_service_access_token: str | None = None


def set_service_session(access_token: str | None) -> None:
    """Yalnız authenticated Electron main: token SQLite/env/log/export'a yazılmaz."""
    if access_token is not None and not re.fullmatch(r"at_[A-Za-z0-9_-]{43}", access_token):
        raise ValueError("Hesap oturum token'ı geçersiz.")
    global _service_access_token
    with _session_lock:
        _service_access_token = access_token


def _access_token() -> str | None:
    with _session_lock:
        return _service_access_token or os.environ.get("RASATHANE_MUHAKEME_API_TOKEN")


def muhakeme_configured() -> bool:
    return bool(_access_token() or os.environ.get("RASATHANE_MUHAKEME_API_URL"))


def _plain(text: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def fetch_rss(url: str) -> list[dict[str, Any]]:
    raw = safe_get(url)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("RSS içinde DTD veya entity tanımları desteklenmez.")
    root = ET.fromstring(raw)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    articles = []
    for entry in [*root.findall(".//item"), *root.findall("a:entry", ns)][:200]:
        title = (
            entry.findtext("title")
            or entry.findtext("a:title", namespaces=ns)
            or "Başlıksız kaynak"
        )
        link = entry.findtext("link")
        if not link:
            atom_link = entry.find("a:link", ns)
            link = atom_link.attrib.get("href", "") if atom_link is not None else ""
        if not link or not link.strip():
            continue
        try:
            link = validate_public_url(urljoin(url, link or ""))
        except ValueError:
            continue
        published = (
            entry.findtext("pubDate")
            or entry.findtext("a:published", namespaces=ns)
            or entry.findtext("a:updated", namespaces=ns)
        )
        if published:
            try:
                published = parsedate_to_datetime(published).isoformat()
            except (ValueError, TypeError):
                pass
        summary = entry.findtext("description") or entry.findtext("a:summary", namespaces=ns) or ""
        articles.append(
            {
                "title": _plain(title),
                "url": link,
                "summary": _plain(summary)[:1500],
                "published_at": published,
                "provenance": {
                    "feed_url": url,
                    "connector": "rss",
                    "text_scope": "publisher_feed_excerpt",
                },
            }
        )
    return articles


def fetch_resmi_gazete(days_back: int = 7) -> list[dict[str, Any]]:
    articles = []
    for offset in range(max(1, min(days_back, 7))):
        day = date.today() - timedelta(days=offset)
        url = f"https://www.resmigazete.gov.tr/eskiler/{day:%Y/%m/%Y%m%d}.htm"
        try:
            raw = safe_get(url)
        except ValueError as exc:
            if "bulunamadı" in str(exc).lower():
                continue
            raise
        encoding = "utf-8" if b"utf-8" in raw[:2048].lower() else "windows-1254"
        content = raw.decode(encoding, errors="replace")
        issue = re.search(r"(\d{4,6})\s*Say[ıi]l[ıi]\s+Resm", content, re.I)
        for match in re.finditer(
            r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content, re.I | re.S
        ):
            href, title = match.groups()
            if not re.fullmatch(rf"{day:%Y%m%d}-\d+\.(?:htm|pdf)", href, re.I):
                continue
            title = _plain(title)
            if not title:
                continue
            articles.append(
                {
                    "title": title,
                    "url": validate_public_url(urljoin(url, href)),
                    "summary": "",
                    "published_at": day.isoformat(),
                    "provenance": {
                        "connector": "resmi_gazete",
                        "gazete_date": day.isoformat(),
                        "gazete_no": issue[1] if issue else None,
                        "index_url": url,
                        "text_scope": "official_index",
                    },
                }
            )
    return articles


def fetch_yargitay_public(limit: int = 20, days_back: int = 60) -> list[dict[str, Any]]:
    """Adalet Bedesten public protokolü; yalnız resmî karar künyesi, tam metin değil.

    İndekste bulunan karar tarihine göre sıralar. Yayım/yükleme tarihi bilinmez;
    dünyanın en son kararının burada indekslendiğini varsaymaz.
    """
    day = date.today()
    start = day - timedelta(days=max(1, min(days_back, 365)))
    endpoint = "https://bedesten.adalet.gov.tr/emsal-karar/searchDocuments"
    data = {
        "pageSize": max(1, min(limit, 50)),
        "pageNumber": 1,
        "itemTypeList": ["YARGITAYKARARI"],
        "phrase": "karar",
        "sortFields": ["KARAR_TARIHI"],
        "sortDirection": "DESC",
        "kararTarihiStart": f"{start.isoformat()}T00:00:00.000Z",
        "kararTarihiEnd": f"{day.isoformat()}T23:59:59.999Z",
    }
    response = safe_json_request(endpoint, {"data": data, "applicationName": "UyapMevzuat"})
    if not isinstance(response, dict):
        raise ValueError("Adalet karar yanıtı geçersiz.")
    metadata = response.get("metadata") or {}
    if isinstance(metadata, dict) and (
        metadata.get("success") is False
        or metadata.get("errors")
        or metadata.get("error")
        or metadata.get("FMTY") == "ERROR"
    ):
        raise ValueError("Adalet karar araması hata döndürdü; kaynak yenilenmedi.")
    body = response.get("data")
    rows = body.get("emsalKararList") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Adalet karar yanıtı emsalKararList içermiyor.")
    articles = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        identifier = str(row.get("documentId", ""))
        if not re.fullmatch(r"\d{1,24}", identifier):
            raise ValueError("Resmî karar kimliği geçersiz; kaynak yenilenmedi.")
        court = str(row.get("birimAdi") or "Yargıtay")
        esas, karar = str(row.get("esasNo") or ""), str(row.get("kararNo") or "")
        decision_date = row.get("kararTarihi")
        display_date = row.get("kararTarihiStr") or decision_date or "bilinmiyor"
        portal_url = f"https://mevzuat.adalet.gov.tr/ictihat/{identifier}"
        articles.append(
            {
                "title": f"Yargıtay {court} · E. {esas} · K. {karar}",
                "url": portal_url,
                "summary": f"Karar tarihi: {display_date}. "
                "Resmî karar künyesi; kararın tam metni değil.",
                "published_at": None,
                "provenance": {
                    "connector": "yargitay_public",
                    "text_scope": "official_metadata",
                    "case_id": identifier,
                    "esas_no": esas,
                    "karar_no": karar,
                    "court": court,
                    "authority": "Yargıtay",
                    "decision_date": decision_date,
                    "date_kind": "decision" if decision_date else "unknown",
                    "date_semantics": "decision_date_not_publication_date",
                    "portal_url": portal_url,
                    "source_endpoint": endpoint,
                    "analysis_supported": False,
                    "search_range": {"start": start.isoformat(), "end": day.isoformat()},
                    "search_phrase": "karar",
                    "sort": "KARAR_TARIHI_DESC",
                },
            }
        )
    return articles


def fetch_muhakeme(kind: str) -> list[dict[str, Any]]:
    """Versiyonlanmış HTTP adapter: tescilli kod içermez; capability env ile açılır."""
    if not muhakeme_configured():
        raise ValueError("Muhakeme API bağlantısı yapılandırılmadı.")
    origin = os.environ.get("RASATHANE_MUHAKEME_API_URL", "https://www.muhakeme.ai").rstrip("/")
    parsed = urlparse(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"muhakeme.ai", "www.muhakeme.ai", "api.muhakeme.ai"}
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Muhakeme API yalnız tanımlı HTTPS sunucularını kabul eder.")
    endpoint = {"yargitay": "kararlar", "mevzuat": "mevzuat"}.get(kind)
    if endpoint is None:
        raise ValueError("Muhakeme kaynak türü desteklenmiyor.")
    headers = {"accept": "application/json"}
    if token := _access_token():
        headers["authorization"] = "Bearer " + token
    payload = safe_json_request(origin + "/api/rasathane/v1/gundem/" + endpoint, headers=headers)
    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Muhakeme API v1 yanıtı items listesi içermiyor.")
    results = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            continue
        published_at = row.get("published_at")
        decision_date = row.get("decision_date")
        date_kind = row.get("date_kind", "unknown")
        if date_kind not in {"decision", "publication", "unknown"}:
            date_kind = "unknown"
        if date_kind == "decision":
            # v2 karar tarihi ayrı taşınır; cache edinim/yükleme zamanı yayım değildir.
            published_at = None
        summary = row.get("summary") or ""
        summary_kind = row.get("summary_kind", "unknown")
        if summary_kind not in {"ai_generated", "source_excerpt", "none", "unknown"}:
            summary_kind = "unknown"
        results.append(
            {
                "title": row.get("title") or row.get("baslik") or "Resmî kaynak",
                "url": validate_public_url(row.get("url", "")),
                "summary": summary,
                "published_at": published_at,
                "provenance": {
                    "connector": "muhakeme_api_v1",
                    "kind": kind,
                    "item_kind": row.get("kind")
                    or ("case" if kind == "yargitay" else "legislation"),
                    "case_id": row.get("case_id"),
                    "authority": row.get("authority"),
                    "schema_version": payload.get("schema_version", "1.0"),
                    "source_kind": payload.get("source_kind"),
                    "source_fetched_at": payload.get("source_fetched_at"),
                    "decision_date": decision_date,
                    "date_kind": date_kind,
                    "date_semantics": "decision_date_not_publication_date"
                    if date_kind == "decision"
                    else "publication_date"
                    if date_kind == "publication"
                    else "upstream_date_unverified",
                    "summary_kind": summary_kind,
                    "text_scope": "managed_summary" if summary else "official_metadata",
                    "analysis_supported": False,
                },
            }
        )
    return results


def fetch_feed(feed: dict[str, Any]) -> list[dict[str, Any]]:
    if feed["kind"] == "rss":
        return fetch_rss(feed["url"])
    if feed["kind"] == "resmi_gazete":
        return fetch_resmi_gazete()
    if feed["kind"] == "yargitay_public":
        return fetch_yargitay_public()
    if feed["kind"] in {"yargitay", "mevzuat"}:
        return fetch_muhakeme(feed["kind"])
    raise ValueError(f"Bu kaynak türü için connector henüz yok: {feed['kind']}")

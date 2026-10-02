from __future__ import annotations

import html
import json
import os
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx

from rasathane.sources import KaynakHatasi, _dns_guvenli, _istek, _url_ayristir, kaynak_edin


def validate_public_url(url: str) -> str:
    try:
        parts = _url_ayristir(url)
    except KaynakHatasi as exc:
        raise ValueError(exc.mesaj) from exc
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


def safe_get(url: str, client: httpx.Client | None = None) -> bytes:
    """Public URL + tüm DNS adresleri denetlenir; otomatik redirect yok; yanıt sınırlandırılır."""
    target = validate_public_url(url)
    owned = client is None
    http = client or httpx.Client(timeout=20, follow_redirects=False, trust_env=False)
    try:
        return _istek(http, target).icerik
    except KaynakHatasi as exc:
        raise ValueError(exc.mesaj) from exc
    finally:
        if owned:
            http.close()


def fetch_preview(url: str) -> dict[str, Any]:
    target = validate_public_url(url)
    try:
        source = kaynak_edin(target)
    except KaynakHatasi as exc:
        raise ValueError(exc.mesaj) from exc
    return {
        "title": source.baslik,
        "url": source.kanonik_url,
        "body": source.metin[:20_000],
        "provenance": {
            "source_type": source.tur.value,
            "acquisition_status": source.edinim_durumu,
            "preview_limit": 20_000,
            "source_metadata": source.ozel,
        },
    }


def safe_json_request(
    url: str, payload: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> Any:
    """Sabit public connector JSON'u: DNS/redirect/stream boyutu tek sınırdan geçer."""
    target = validate_public_url(url)
    try:
        _dns_guvenli(_url_ayristir(target))
    except KaynakHatasi as exc:
        raise ValueError(exc.mesaj) from exc
    with httpx.Client(timeout=20, follow_redirects=False, trust_env=False) as client:
        with client.stream(
            "POST" if payload is not None else "GET",
            target,
            json=payload,
            headers={
                "Accept": "application/json",
                "User-Agent": "Rasathane/0.5",
                **(headers or {}),
            },
        ) as response:
            if 300 <= response.status_code < 400:
                raise ValueError("Kaynak yönlendirmesi güvenlik nedeniyle izlenmedi.")
            if response.status_code == 429:
                raise SourceRateLimited(response.headers.get("retry-after"))
            response.raise_for_status()
            if int(response.headers.get("content-length", "0")) > 2_000_000:
                raise ValueError("Kaynak JSON yanıtı izin verilen boyutu aşıyor.")
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise ValueError("Kaynak JSON yanıtı izin verilen boyutu aşıyor.")
    return json.loads(content.decode("utf-8-sig"))


class SearchProvider(Protocol):
    name: str

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]: ...


class SourceRateLimited(ValueError):
    def __init__(self, retry_after: str | None) -> None:
        delay = 600
        if retry_after:
            try:
                delay = int(retry_after)
            except ValueError:
                try:
                    delay = int(
                        (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                    )
                except (ValueError, TypeError):
                    pass
        self.retry_after_seconds = max(60, min(delay, 86400))
        super().__init__(
            f"Resmî kaynak hız sınırı uyguladı; {self.retry_after_seconds} saniye sonra deneyin."
        )


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._field: str | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        classes = (data.get("class") or "").split()
        if "result__a" in classes and tag == "a":
            href = data.get("href") or ""
            if href.startswith("//"):
                href = "https:" + href
            parsed = urlsplit(href)
            if parsed.hostname in {"duckduckgo.com", "html.duckduckgo.com"}:
                href = parse_qs(parsed.query).get("uddg", [""])[0]
            try:
                href = validate_public_url(href)
            except ValueError:
                self._field = None
                return
            self.items.append({"title": "", "url": href, "excerpt": ""})
            self._field, self._depth = "title", 1
        elif "result__snippet" in classes and self.items:
            self._field, self._depth = "excerpt", 1
        elif self._field and tag not in {"br", "img", "input", "meta", "link", "hr"}:
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._field:
            self._depth -= 1
            if self._depth <= 0:
                self._field = None

    def handle_data(self, data: str) -> None:
        if self._field and self.items:
            self.items[-1][self._field] += data


class DuckDuckGoSearch:
    name = "duckduckgo"

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query, "kl": "tr-tr"})
        content = safe_get(url).decode("utf-8", errors="replace")
        if "anomaly.js" in content or "anomaly-modal" in content:
            raise RuntimeError("Arama sağlayıcısı doğrulama istedi; daha sonra yeniden deneyin.")
        parser = _DuckDuckGoParser()
        parser.feed(content)
        results, seen = [], set()
        for row in parser.items:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            results.append(
                {key: " ".join(html.unescape(value).split()) for key, value in row.items()}
            )
            if len(results) >= limit:
                break
        if not results and not any(
            marker in content.lower() for marker in ("no results", "no-results", "no more results")
        ):
            raise RuntimeError(
                "Arama yanıtı tanınamadı; sağlayıcının HTML biçimi değişmiş olabilir."
            )
        return results


class ConfiguredSearch:
    name = "configured"

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        from ytcore.intel.websearch import websearch_al

        provider = websearch_al()
        if hasattr(provider, "ara_durumlu"):
            rows, status = provider.ara_durumlu(query, limit)
            if status not in {"aktif", "fixture"}:
                raise RuntimeError(f"Yapılandırılmış arama sağlayıcısı: {status}")
        else:
            rows = provider.ara(query, limit)
        return [
            {"title": row.baslik, "url": validate_public_url(row.url), "excerpt": row.ozet}
            for row in rows
        ]


def search_provider(choice: str = "auto") -> SearchProvider:
    if choice == "configured" or (
        choice == "auto"
        and any(os.environ.get(k) for k in ("SERPER_API_KEY", "YT_SEARXNG_URL", "YT_FIRECRAWL_URL"))
    ):
        return ConfiguredSearch()
    return DuckDuckGoSearch()

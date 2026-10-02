from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class AramaSonuc:
    baslik: str
    url: str
    ozet: str


@runtime_checkable
class WebSearch(Protocol):
    def ara(self, sorgu: str, n: int = 5) -> list[AramaSonuc]: ...


class FakeWebSearch:
    """Hermetik deterministik web sonucu (ağsız). Test + exe selftest."""

    def ara(self, sorgu: str, n: int = 5) -> list[AramaSonuc]:
        return [
            AramaSonuc(
                baslik=f"Kaynak {i + 1}: {sorgu[:40]}",
                url=f"https://ornek.test/{i + 1}",
                ozet=f"{sorgu[:60]} hakkında özet bilgi {i + 1}.",
            )
            for i in range(min(n, 2))
        ]

    def ara_durumlu(self, sorgu: str, n: int = 5) -> tuple[list[AramaSonuc], str]:
        return self.ara(sorgu, n), "fixture"


class SerperSearch:
    """Serper (Google SERP) REST — anahtar YOKSA inert (boş + 'anahtar_yok').

    KVKK: sorgu metni anonimleştirilmiş olmalı (factcheck katmanı sağlar). torch yok
    (httpx REST). Faz 5'te SERPER_API_KEY gelince aktif. Hardcode YASAK (env).
    """

    def __init__(self, api_key: str | None = None) -> None:
        from ytcore.config import get_config

        self.api_key = api_key if api_key is not None else get_config().serper_api_key

    def ara_durumlu(self, sorgu: str, n: int = 5) -> tuple[list[AramaSonuc], str]:
        if not self.api_key:
            return [], "anahtar_yok"
        import httpx

        try:
            r = httpx.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": self.api_key, "Content-Type": "application/json"},
                json={"q": sorgu, "num": n, "hl": "tr"},
                timeout=15.0,
            )
            r.raise_for_status()
            veri = r.json()
        except Exception as e:  # noqa: BLE001 — ağ/HTTP ham hata sınırda graceful
            return [], f"hata: {type(e).__name__}"
        sonuc = [
            AramaSonuc(baslik=o.get("title", ""), url=o.get("link", ""), ozet=o.get("snippet", ""))
            for o in veri.get("organic", [])[:n]
        ]
        return sonuc, "aktif"

    def ara(self, sorgu: str, n: int = 5) -> list[AramaSonuc]:
        return self.ara_durumlu(sorgu, n)[0]


class SearXNGSearch:
    """SearXNG self-hosted metasearch (yerel HTTP, ANAHTARSIZ). Ollama emsali: loopback'te
    kosan yerel servis, sorgu-basi ucretsiz. JSON API: GET /search?format=json.

    KVKK FAIL-CLOSED: yalniz LOOPBACK instance kabul (deny-by-default — uzak SearXNG'e
    PII-temiz sorgu bile gitmesin; Ollama loopback-guard'inin web esi). Anonim+NER gate
    factcheck.py'de saglayicidan BAGIMSIZ calisir; SearXNG yalniz temizlenmis sorguyu alir.
    Kurulum: docker run -d -p 127.0.0.1:8888:8080 searxng/searxng (settings.yml:
    formats:[html,json] + limiter:false). YT_SEARXNG_URL ile opt-in; kurulu degilse
    'baglanti_yok' (graceful, web_yok'tan AYRI)."""

    def __init__(self, taban_url: str | None = None) -> None:
        from ytcore.config import _normalize_host, get_config

        self.taban = _normalize_host(
            taban_url or get_config().searxng_url or "http://127.0.0.1:8888"
        )

    def ara_durumlu(self, sorgu: str, n: int = 5) -> tuple[list[AramaSonuc], str]:
        from ytcore.config import _loopback_host_mi

        if not _loopback_host_mi(self.taban):
            return [], "uzak_engellendi"  # KVKK: yalniz yerel instance (deny-by-default)
        import httpx

        try:
            r = httpx.get(
                f"{self.taban}/search",
                params={"q": sorgu, "format": "json", "language": "tr", "safesearch": 0},
                headers={"User-Agent": "ytanaliz/1.0"},
                timeout=15.0,
            )
            if r.status_code == 403:
                return [], "searxng_403"  # settings.yml formats/limiter ayari eksik
            r.raise_for_status()
            veri = r.json()
        except httpx.ConnectError:
            return [], "baglanti_yok"  # instance kapali (kurulabilir; web_yok'tan AYRI)
        except Exception as e:  # noqa: BLE001 — ag/HTTP ham hata sinirda graceful
            return [], f"hata: {type(e).__name__}"
        sonuc = [
            AramaSonuc(baslik=o.get("title", ""), url=o.get("url", ""), ozet=o.get("content", ""))
            for o in veri.get("results", [])[:n]
        ]
        return sonuc, "aktif"

    def ara(self, sorgu: str, n: int = 5) -> list[AramaSonuc]:
        return self.ara_durumlu(sorgu, n)[0]


class FirecrawlSearch:
    """Self-hosted Firecrawl (yerel HTTP, ANAHTARSIZ) /v1/search. VARSAYILAN yerel sağlayıcı
    (127.0.0.1:3002 kuruluysa otomatik). Firecrawl arama + scrape motoru; bizim için search
    yeterli (claim → kanıt URL'leri). Yanıt: {success, data:[{url,title,description}]}.

    KVKK FAIL-CLOSED: yalniz LOOPBACK instance (deny-by-default — uzak Firecrawl'a PII-temiz
    sorgu bile gitmesin; SearXNG/Ollama loopback-guard'ı ile aynı). Anonim+NER gate factcheck.py'de
    saglayicidan BAGIMSIZ. Kurulu degilse 'baglanti_yok' (graceful, web_yok'tan AYRI)."""

    def __init__(self, taban_url: str | None = None) -> None:
        from ytcore.config import _normalize_host, get_config

        self.taban = _normalize_host(
            taban_url or get_config().firecrawl_url or "http://127.0.0.1:3002"
        )

    def ara_durumlu(self, sorgu: str, n: int = 5) -> tuple[list[AramaSonuc], str]:
        from ytcore.config import _loopback_host_mi

        if not _loopback_host_mi(self.taban):
            return [], "uzak_engellendi"  # KVKK: yalniz yerel instance
        import httpx

        try:
            r = httpx.post(
                f"{self.taban}/v1/search",
                json={"query": sorgu, "limit": n},
                headers={"Content-Type": "application/json"},
                timeout=30.0,  # Firecrawl arama+scrape yapabilir → SearXNG'den yavaş
            )
            if r.status_code in (401, 402, 403):
                return [], "anahtar_yok"  # bulut Firecrawl (anahtar/kredi ister) — yerelde olmaz
            r.raise_for_status()
            veri = r.json()
        except httpx.ConnectError:
            return [], "baglanti_yok"  # Firecrawl kapalı (kurulabilir; web_yok'tan AYRI)
        except Exception as e:  # noqa: BLE001 — ag/HTTP ham hata sinirda graceful
            return [], f"hata: {type(e).__name__}"
        kayitlar = veri.get("data") or []
        sonuc = [
            AramaSonuc(
                baslik=o.get("title", ""),
                url=o.get("url", ""),
                ozet=(o.get("description") or (o.get("markdown") or "")[:300]),
            )
            for o in kayitlar[:n]
        ]
        return sonuc, "aktif"

    def ara(self, sorgu: str, n: int = 5) -> list[AramaSonuc]:
        return self.ara_durumlu(sorgu, n)[0]


def websearch_al() -> WebSearch:
    """Saglayici secimi: YT_WEBSEARCH_FIXTURE -> FakeWebSearch (hermetik); YT_SEARXNG_URL ->
    SearXNGSearch; SERPER_API_KEY -> SerperSearch; firecrawl_url (default 127.0.0.1:3002) ->
    FirecrawlSearch (kuruluysa otomatik); aksi -> SerperSearch ('anahtar_yok'=web_yok). Tum yerel
    saglayicilar loopback-guard'li; egress yalniz yapilandirma/default ile mumkun (web_mumkun/NER
    gate ile hizali — keyfi egress + ner=None deligi yok)."""
    if os.environ.get("YT_WEBSEARCH_FIXTURE", "").strip():
        return FakeWebSearch()
    from ytcore.config import get_config

    cfg = get_config()
    if cfg.searxng_url:
        return SearXNGSearch()
    if cfg.serper_api_key:
        return SerperSearch()
    if cfg.firecrawl_url:
        return FirecrawlSearch()
    return SerperSearch()

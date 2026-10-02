from __future__ import annotations

import socket
from datetime import date

import httpx
import pytest
from rasathane.product import connectors, web


def test_ddg_html_extraction_and_private_result_rejection(monkeypatch):
    content = (
        b'<a class="result__a" href="//duckduckgo.com/l/?'
        b'uddg=https%3A%2F%2Fexample.com%2Flaw">Work <b>law</b></a>'
        b'<a class="result__snippet">Useful law</a>'
        b'<a class="result__a" href="http://127.0.0.1/private">Unsafe</a>'
    )
    monkeypatch.setattr(web, "safe_get", lambda url: content)
    results = web.DuckDuckGoSearch().search("work")
    assert results == [
        {"title": "Work law", "url": "https://example.com/law", "excerpt": "Useful law"}
    ]


def test_safe_get_blocks_private_dns_and_redirect(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    calls = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: calls.append(request) or httpx.Response(200, text="x")
        )
    ) as client:
        with pytest.raises(ValueError):
            web.safe_get("https://example.com", client)
        assert calls == []
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        )
    ) as client:
        with pytest.raises(ValueError):
            web.safe_get("https://example.com", client)


def test_rss_actual_parser_dedupe_metadata_and_entity_guard(monkeypatch):
    monkeypatch.setattr(
        connectors,
        "safe_get",
        lambda url: (
            b"<rss><channel><item><title>Law</title><link>https://example.com/law</link>"
            b"<description>Law update</description></item></channel></rss>"
        ),
    )
    assert connectors.fetch_rss("https://example.com/feed")[0]["provenance"]["connector"] == "rss"
    monkeypatch.setattr(
        connectors, "safe_get", lambda url: b'<!DOCTYPE x [<!ENTITY x "evil">]><rss/>'
    )
    with pytest.raises(ValueError):
        connectors.fetch_rss("https://example.com/feed")


def test_rss_without_article_link_is_not_treated_as_feed_article(monkeypatch):
    monkeypatch.setattr(
        connectors,
        "safe_get",
        lambda url: b"<rss><channel><item><title>Incomplete item</title></item></channel></rss>",
    )
    assert connectors.fetch_rss("https://example.com/feed") == []


def test_official_gazette_parser_preserves_public_source_provenance(monkeypatch):
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 3)

    monkeypatch.setattr(connectors, "date", Today)
    content = (
        "<title>33404 Sayılı Resmi Gazete</title>"
        '<a href="20261003-1.htm">Yönetmelik</a>'
        '<a href="20261003-2.pdf">Tebliğ</a>'
        '<a href="20251003-9.htm">Eski madde</a>'
    ).encode()
    monkeypatch.setattr(connectors, "safe_get", lambda url: b'<meta charset="utf-8">' + content)
    rows = connectors.fetch_resmi_gazete(1)
    assert len(rows) == 2
    assert rows[0]["provenance"]["gazete_no"] == "33404"
    assert rows[1]["url"].endswith("20261003-2.pdf")


def test_muhakeme_native_token_overrides_env_and_keeps_case_provenance(monkeypatch):
    native = "at_" + "B" * 43
    calls = []
    original_client = httpx.Client

    def handle(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "Karar",
                        "url": "https://example.com/decision",
                        "summary": "Özet",
                        "published_at": "2026-10-03",
                        "case_id": "2026/1 E. 2026/2 K.",
                        "authority": "Yargıtay 9. Hukuk Dairesi",
                    }
                ]
            },
        )

    monkeypatch.delenv("RASATHANE_MUHAKEME_API_URL", raising=False)
    monkeypatch.setenv("RASATHANE_MUHAKEME_API_TOKEN", "development-only-env-token")
    monkeypatch.setattr(
        web.httpx,
        "Client",
        lambda **kwargs: original_client(**kwargs, transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(web, "_dns_guvenli", lambda parts: None)
    connectors.set_service_session(native)
    try:
        result = connectors.fetch_muhakeme("yargitay")
        assert str(calls[0].url) == "https://www.muhakeme.ai/api/rasathane/v1/gundem/kararlar"
        assert calls[0].headers["authorization"] == "Bearer " + native
        assert result[0]["provenance"]["case_id"] == "2026/1 E. 2026/2 K."
        assert result[0]["published_at"] == "2026-10-03"
        assert native not in str(result)
    finally:
        connectors.set_service_session(None)


def test_public_yargitay_exact_protocol_date_semantics_and_error_envelope(monkeypatch):
    calls = []
    payload = {
        "data": {
            "emsalKararList": [
                {
                    "documentId": 1228680200,
                    "birimAdi": "10. Ceza Dairesi",
                    "esasNo": "2026/8295",
                    "kararNo": "2026/12094",
                    "kararTarihi": "2026-09-23T00:00:00+03:00",
                    "kararTarihiStr": "23.09.2026",
                }
            ],
            "total": 556,
        },
        "metadata": {"FMTY": "SUCCESS"},
    }

    def query(url, body):
        calls.append((url, body))
        return payload

    monkeypatch.setattr(connectors, "safe_json_request", query)
    rows = connectors.fetch_yargitay_public(limit=2)
    assert calls[0][0] == "https://bedesten.adalet.gov.tr/emsal-karar/searchDocuments"
    assert calls[0][1]["data"]["sortFields"] == ["KARAR_TARIHI"]
    assert rows[0]["url"] == "https://mevzuat.adalet.gov.tr/ictihat/1228680200"
    assert rows[0]["provenance"]["case_id"] == "1228680200"
    assert rows[0]["provenance"]["decision_date"] == rows[0]["published_at"]
    assert rows[0]["provenance"]["analysis_supported"] is False
    assert rows[0]["provenance"]["text_scope"] == "official_metadata"
    payload = {"data": None, "metadata": {"FMTY": "ERROR", "FMC": "quota"}}
    with pytest.raises(ValueError, match="hata"):
        connectors.fetch_yargitay_public()


def test_json_transport_has_stream_cap_redirect_guard_and_retry_after(monkeypatch):
    original_client = httpx.Client
    monkeypatch.setattr(web, "_dns_guvenli", lambda parts: None)
    response = httpx.Response(429, headers={"Retry-After": "720"})
    monkeypatch.setattr(
        web.httpx,
        "Client",
        lambda **kwargs: original_client(
            **kwargs, transport=httpx.MockTransport(lambda request: response)
        ),
    )
    with pytest.raises(web.SourceRateLimited) as error:
        web.safe_json_request("https://example.com/api", {"data": {}})
    assert error.value.retry_after_seconds == 720
    response = httpx.Response(302, headers={"Location": "http://127.0.0.1/"})
    with pytest.raises(ValueError, match="yönlendirme"):
        web.safe_json_request("https://example.com/api")
    response = httpx.Response(200, content=b"x" * 2_000_001)
    with pytest.raises(ValueError, match="boyutu"):
        web.safe_json_request("https://example.com/api")

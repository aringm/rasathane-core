from __future__ import annotations

import json
import socket
from typing import Any

import httpx
import pytest
from rasathane.sources import (
    KaynakBelgesi,
    KaynakHatasi,
    KaynakSinyali,
    KaynakTuru,
    kaynak_edin,
    kaynak_turu_bul,
)


@pytest.fixture
def genel_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSRF DNS denetimini gerçek ağa çıkmadan genel bir IP ile geçir."""

    def _getaddrinfo(
        host: str,
        port: int,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        del host, family, type, proto, flags
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", _getaddrinfo)


def _istemci(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_public_sozlesme_pydantic_modelleri() -> None:
    assert [tur.value for tur in KaynakTuru] == [
        "youtube",
        "github",
        "arxiv",
        "reddit",
        "huggingface",
        "web",
    ]
    sinyal = KaynakSinyali(
        etiket="popülerlik",
        deger=42,
        aciklama="Kaynağın görünür etkileşim düzeyi.",
        durum="bilgi",
    )
    belge = KaynakBelgesi(
        tur=KaynakTuru.web,
        kimlik="abc",
        kanonik_url="https://example.com/yazi",
        baslik="Örnek yazı",
        sahip="Örnek Yazar",
        yayin_tarihi="2026-01-01T00:00:00Z",
        guncelleme_tarihi=None,
        dil="tr",
        metin="İçerik",
        etiketler=["örnek"],
        metrikler={"kelime_sayisi": 1},
        ozel={"fixture": False},
        sinyaller=[sinyal],
        edinim_durumu="tam",
    )

    assert belge.sinyaller[0].deger == 42
    assert belge.model_dump(mode="json")["tur"] == "web"


def test_kaynak_hatasi_kod_ve_mesaj_tasir() -> None:
    hata = KaynakHatasi("ornek_kod", "Açık hata mesajı")

    assert hata.kod == "ornek_kod"
    assert hata.mesaj == "Açık hata mesajı"
    assert str(hata) == "Açık hata mesajı"


@pytest.mark.parametrize(
    ("url", "beklenen"),
    [
        ("https://youtu.be/abc", KaynakTuru.youtube),
        ("https://www.youtube.com/watch?v=abc", KaynakTuru.youtube),
        ("https://github.com/openai/openai-python", KaynakTuru.github),
        ("https://arxiv.org/abs/2401.12345", KaynakTuru.arxiv),
        ("https://www.reddit.com/r/python/comments/abc123/ornek/", KaynakTuru.reddit),
        ("https://redd.it/abc123", KaynakTuru.reddit),
        ("https://huggingface.co/datasets/openai/gsm8k", KaynakTuru.huggingface),
        ("https://example.com/yazi", KaynakTuru.web),
    ],
)
def test_kaynak_turu_bul(url: str, beklenen: KaynakTuru) -> None:
    assert kaynak_turu_bul(url) is beklenen


@pytest.mark.parametrize(
    ("url", "kod"),
    [
        ("ftp://example.com/dosya", "desteklenmeyen_protokol"),
        ("https://kullanici:sifre@example.com", "kimlik_bilgisi_yasak"),
        ("http://localhost:8000", "guvensiz_hedef"),
        ("http://127.0.0.1", "guvensiz_hedef"),
        ("http://169.254.169.254/latest/meta-data", "guvensiz_hedef"),
        ("http://10.0.0.8", "guvensiz_hedef"),
        ("metin", "desteklenmeyen_protokol"),
    ],
)
def test_url_guvenlik_sinirlari(url: str, kod: str) -> None:
    with pytest.raises(KaynakHatasi) as exc:
        kaynak_turu_bul(url)

    assert exc.value.kod == kod


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/ornek/proje",
        "https://arxiv.org/abs/2401.12345",
        "https://reddit.com/r/python/comments/abc123/ornek/",
        "https://huggingface.co/ornek/model",
        "https://example.com/yazi",
    ],
)
def test_fixture_tum_youtube_disi_kaynaklarda_agsizdir(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")

    def _ag_yasak(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"Fixture ağ çağrısı yaptı: {request.url}")

    with _istemci(_ag_yasak) as client:
        belge = kaynak_edin(url, client=client)

    assert belge.edinim_durumu == "fixture"
    assert belge.ozel["fixture"] is True
    assert belge.metin


def test_youtube_ortak_adapter_legacy_pipeline_isareti_verir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RASATHANE_SOURCE_FIXTURE", "1")

    with pytest.raises(KaynakHatasi) as exc:
        kaynak_edin("https://youtu.be/abc")

    assert exc.value.kod == "youtube_legacy"


def test_github_repo_metadata_ve_readme_edinir(genel_ip: None) -> None:
    istekler: list[httpx.Request] = []

    def _yanit(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        if request.url.path == "/repos/openai/openai-python":
            return httpx.Response(
                200,
                json={
                    "id": 123,
                    "name": "openai-python",
                    "full_name": "openai/openai-python",
                    "html_url": "https://github.com/openai/openai-python",
                    "description": "OpenAI Python istemcisi.",
                    "owner": {"login": "openai"},
                    "created_at": "2020-01-01T00:00:00Z",
                    "updated_at": "2026-07-01T00:00:00Z",
                    "pushed_at": "2026-07-02T00:00:00Z",
                    "language": "Python",
                    "topics": ["openai", "python"],
                    "stargazers_count": 25000,
                    "forks_count": 4000,
                    "open_issues_count": 300,
                    "subscribers_count": 500,
                    "default_branch": "main",
                    "license": {"spdx_id": "Apache-2.0"},
                    "archived": False,
                    "fork": False,
                    "visibility": "public",
                },
            )
        if request.url.path == "/repos/openai/openai-python/readme":
            assert "raw" in request.headers["accept"]
            return httpx.Response(200, text="# OpenAI Python\n\nKullanım açıklaması.")
        return httpx.Response(404)

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://github.com/openai/openai-python", client=client)

    assert belge.tur is KaynakTuru.github
    assert belge.kimlik == "openai/openai-python"
    assert belge.sahip == "openai"
    assert "Kullanım açıklaması" in belge.metin
    assert belge.metrikler["yildiz"] == 25000
    assert belge.ozel["lisans"] == "Apache-2.0"
    assert [istek.url.host for istek in istekler] == ["api.github.com", "api.github.com"]


def test_github_token_api_ve_readme_isteklerine_eklenir(
    monkeypatch: pytest.MonkeyPatch, genel_ip: None
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "  github-test-token  ")
    istekler: list[httpx.Request] = []

    def _yanit(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        if request.url.path.endswith("/readme"):
            return httpx.Response(200, text="# Yetkili README")
        return httpx.Response(
            200,
            json={
                "id": 1,
                "name": "proje",
                "full_name": "ornek/proje",
                "html_url": "https://github.com/ornek/proje",
                "owner": {"login": "ornek"},
            },
        )

    with _istemci(_yanit) as client:
        kaynak_edin("https://github.com/ornek/proje", client=client)

    assert len(istekler) == 2
    assert {istek.headers.get("authorization") for istek in istekler} == {
        "Bearer github-test-token"
    }


def test_github_readme_yoksa_metadata_kismi_belge_olur(genel_ip: None) -> None:
    def _yanit(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/readme"):
            return httpx.Response(404)
        return httpx.Response(
            200,
            json={
                "id": 9,
                "name": "bos",
                "full_name": "ornek/bos",
                "html_url": "https://github.com/ornek/bos",
                "description": "Yalnız metadata.",
                "owner": {"login": "ornek"},
            },
        )

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://github.com/ornek/bos", client=client)

    assert belge.edinim_durumu == "kismi"
    assert belge.metin == "Yalnız metadata."


def test_arxiv_atom_metadata_ve_ozet_edinir(genel_ip: None) -> None:
    atom = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2401.12345v2</id>
        <updated>2026-06-02T12:00:00Z</updated>
        <published>2026-05-01T10:00:00Z</published>
        <title>  Güvenilir Kaynak Analizi  </title>
        <summary>  Birinci satır.\n İkinci satır. </summary>
        <author><name>Ada Lovelace</name></author>
        <author><name>Alan Turing</name></author>
        <category term="cs.AI" />
        <category term="cs.CL" />
        <link rel="alternate" href="https://arxiv.org/abs/2401.12345v2" />
        <link title="pdf" href="https://arxiv.org/pdf/2401.12345v2" />
        <arxiv:doi>10.1000/example</arxiv:doi>
      </entry>
    </feed>"""

    def _yanit(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "export.arxiv.org"
        assert request.url.params["id_list"] == "2401.12345"
        return httpx.Response(200, text=atom, headers={"content-type": "application/atom+xml"})

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://arxiv.org/abs/2401.12345", client=client)

    assert belge.tur is KaynakTuru.arxiv
    assert belge.kimlik == "2401.12345v2"
    assert belge.baslik == "Güvenilir Kaynak Analizi"
    assert belge.sahip == "Ada Lovelace, Alan Turing"
    assert belge.metin == "Birinci satır. İkinci satır."
    assert belge.etiketler == ["cs.AI", "cs.CL"]
    assert belge.ozel["doi"] == "10.1000/example"
    assert belge.ozel["text_scope"] == "abstract_only"
    assert belge.ozel["full_text_fetched"] is False
    assert any(s.deger == "abstract_only" for s in belge.sinyaller)


@pytest.mark.parametrize(
    ("url", "api_yolu", "hf_turu"),
    [
        ("https://huggingface.co/openai/model", "/api/models/openai/model", "model"),
        (
            "https://huggingface.co/datasets/openai/veri",
            "/api/datasets/openai/veri",
            "dataset",
        ),
        ("https://huggingface.co/spaces/openai/demo", "/api/spaces/openai/demo", "space"),
    ],
)
def test_huggingface_api_ve_readme_edinir(
    genel_ip: None, url: str, api_yolu: str, hf_turu: str
) -> None:
    def _yanit(request: httpx.Request) -> httpx.Response:
        if request.url.path == api_yolu:
            return httpx.Response(
                200,
                json={
                    "id": api_yolu.split("/", 3)[-1],
                    "author": "openai",
                    "createdAt": "2025-01-01T00:00:00Z",
                    "lastModified": "2026-07-01T00:00:00Z",
                    "downloads": 1234,
                    "likes": 56,
                    "tags": ["text-generation", "turkish"],
                    "pipeline_tag": "text-generation",
                    "library_name": "transformers",
                    "private": False,
                    "gated": False,
                    "sha": "abcdef",
                },
            )
        if request.url.path.endswith("/raw/main/README.md"):
            return httpx.Response(200, text="# Kart\n\nKaynak açıklaması.")
        return httpx.Response(404)

    with _istemci(_yanit) as client:
        belge = kaynak_edin(url, client=client)

    assert belge.tur is KaynakTuru.huggingface
    assert belge.ozel["huggingface_turu"] == hf_turu
    assert belge.metrikler == {"indirme": 1234, "begeni": 56}
    assert "Kaynak açıklaması" in belge.metin


def test_huggingface_token_api_ve_readme_isteklerine_eklenir(
    monkeypatch: pytest.MonkeyPatch, genel_ip: None
) -> None:
    monkeypatch.setenv("HF_TOKEN", "  hf-test-token  ")
    istekler: list[httpx.Request] = []

    def _yanit(request: httpx.Request) -> httpx.Response:
        istekler.append(request)
        if request.url.path.endswith("/raw/main/README.md"):
            return httpx.Response(200, text="# Yetkili model kartı")
        return httpx.Response(
            200,
            json={
                "id": "ornek/model",
                "author": "ornek",
                "private": False,
            },
        )

    with _istemci(_yanit) as client:
        kaynak_edin("https://huggingface.co/ornek/model", client=client)

    assert len(istekler) == 2
    assert {istek.headers.get("authorization") for istek in istekler} == {"Bearer hf-test-token"}


def test_reddit_token_yokken_generic_fallback_yapmaz(
    monkeypatch: pytest.MonkeyPatch, genel_ip: None
) -> None:
    monkeypatch.delenv("REDDIT_ACCESS_TOKEN", raising=False)
    cagrildi = False

    def _yanit(request: httpx.Request) -> httpx.Response:
        nonlocal cagrildi
        cagrildi = True
        return httpx.Response(200, text="<html>generic olmamalı</html>")

    with _istemci(_yanit) as client, pytest.raises(KaynakHatasi) as exc:
        kaynak_edin("https://reddit.com/r/python/comments/abc123/ornek/", client=client)

    assert exc.value.kod == "auth_gerekli"
    assert cagrildi is False


def test_reddit_yalniz_oauth_api_uzerinden_edinir(
    monkeypatch: pytest.MonkeyPatch, genel_ip: None
) -> None:
    monkeypatch.setenv("REDDIT_ACCESS_TOKEN", "test-token")

    def _yanit(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "oauth.reddit.com"
        assert request.url.path == "/comments/abc123"
        assert request.headers["authorization"] == "Bearer test-token"
        payload = [
            {
                "data": {
                    "children": [
                        {
                            "data": {
                                "id": "abc123",
                                "title": "Python kaynakları",
                                "selftext": "Açıklayıcı gönderi metni.",
                                "author": "ornek_kullanici",
                                "created_utc": 1783650000,
                                "edited": False,
                                "subreddit": "python",
                                "score": 120,
                                "upvote_ratio": 0.95,
                                "num_comments": 12,
                                "permalink": "/r/python/comments/abc123/ornek/",
                                "url": "https://www.reddit.com/r/python/comments/abc123/ornek/",
                                "link_flair_text": "Kaynak",
                                "is_self": True,
                                "over_18": False,
                            }
                        }
                    ]
                }
            },
            {"data": {"children": []}},
        ]
        return httpx.Response(200, json=payload)

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://www.reddit.com/r/python/comments/abc123/ornek/", client=client)

    assert belge.tur is KaynakTuru.reddit
    assert belge.baslik == "Python kaynakları"
    assert belge.metin == "Açıklayıcı gönderi metni."
    assert belge.metrikler["puan"] == 120
    assert belge.ozel["subreddit"] == "python"


def test_reddit_yorum_agaci_kullanici_adlarini_tasimadan_duzlestirilir(
    monkeypatch: pytest.MonkeyPatch, genel_ip: None
) -> None:
    monkeypatch.setenv("REDDIT_ACCESS_TOKEN", "test-token")
    payload = [
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "abc123",
                            "title": "Yorum ağacı",
                            "selftext": "Gönderi metni.",
                            "author": "gonderi_sahibi",
                            "permalink": "/r/python/comments/abc123/ornek/",
                        }
                    }
                ]
            }
        },
        {
            "data": {
                "children": [
                    {
                        "data": {
                            "body": "Birinci yorum.",
                            "author": "yorumcu_bir",
                            "replies": {
                                "data": {
                                    "children": [
                                        {
                                            "data": {
                                                "body": "İkinci yorum.",
                                                "author": "yorumcu_iki",
                                            }
                                        },
                                        {
                                            "data": {
                                                "body": "[deleted]",
                                                "author": "silinen_yorumcu",
                                            }
                                        },
                                    ]
                                }
                            },
                        }
                    },
                    {"data": {"body": "[removed]", "author": "kaldirilan_yorumcu"}},
                ]
            }
        },
    ]

    def _yanit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://www.reddit.com/r/python/comments/abc123/ornek/", client=client)

    assert belge.sahip == "gonderi_sahibi"
    assert "Yorum 1: Birinci yorum." in belge.metin
    assert "Yorum 2: İkinci yorum." in belge.metin
    assert belge.ozel["yorum_icerigi_sayisi"] == 2
    assert not {
        "yorumcu_bir",
        "yorumcu_iki",
        "silinen_yorumcu",
        "kaldirilan_yorumcu",
        "[deleted]",
        "[removed]",
    }.intersection(belge.metin.split())


def test_generic_web_main_metnini_ve_metadata_edinir(genel_ip: None) -> None:
    html = """<!doctype html>
    <html lang="tr"><head>
      <title>Sayfa başlığı</title>
      <link rel="canonical" href="https://example.com/kanonik-yazi">
      <meta name="author" content="Av. Mehmet Arın Gülüm">
      <meta name="keywords" content="hukuk, yapay zekâ">
      <meta property="article:published_time" content="2026-07-10T10:00:00+03:00">
    </head><body>
      <nav>Menü metni alınmamalı.</nav>
      <main><h1>Ana başlık</h1><p>Birinci paragraf.</p>
        <script>gizliKod()</script><p>İkinci paragraf.</p>
      </main>
      <footer>Footer metni alınmamalı.</footer>
    </body></html>"""

    def _yanit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=html.encode("utf-8"),
            headers={"content-type": "text/html; charset=utf-8"},
        )

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://example.com/yazi", client=client)

    assert belge.tur is KaynakTuru.web
    assert belge.kanonik_url == "https://example.com/kanonik-yazi"
    assert belge.baslik == "Sayfa başlığı"
    assert belge.sahip == "Av. Mehmet Arın Gülüm"
    assert belge.dil == "tr"
    assert belge.metin == "Ana başlık Birinci paragraf. İkinci paragraf."
    assert "Menü" not in belge.metin
    assert "gizliKod" not in belge.metin
    assert belge.etiketler == ["hukuk", "yapay zekâ"]


def test_dns_ozel_ip_cozumlenirse_istek_engellenir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))
        ],
    )
    cagrildi = False

    def _yanit(request: httpx.Request) -> httpx.Response:
        nonlocal cagrildi
        cagrildi = True
        return httpx.Response(200)

    with _istemci(_yanit) as client, pytest.raises(KaynakHatasi) as exc:
        kaynak_edin("https://example.com/yazi", client=client)

    assert exc.value.kod == "guvensiz_hedef"
    assert cagrildi is False


def test_redirect_otomatik_izlenmez(genel_ip: None) -> None:
    istek_sayisi = 0

    def _yanit(request: httpx.Request) -> httpx.Response:
        nonlocal istek_sayisi
        istek_sayisi += 1
        return httpx.Response(302, headers={"location": "https://example.com/hedef"})

    with _istemci(_yanit) as client, pytest.raises(KaynakHatasi) as exc:
        kaynak_edin("https://example.com/yazi", client=client)

    assert exc.value.kod == "yonlendirme_engellendi"
    assert istek_sayisi == 1


def test_yanit_boyutu_sinirlanir(genel_ip: None) -> None:
    def _yanit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 2_100_000,
            headers={"content-type": "text/html"},
        )

    with _istemci(_yanit) as client, pytest.raises(KaynakHatasi) as exc:
        kaynak_edin("https://example.com/buyuk", client=client)

    assert exc.value.kod == "yanit_cok_buyuk"


def test_gecersiz_json_typed_hata_verir(genel_ip: None) -> None:
    def _yanit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"json degil")

    with _istemci(_yanit) as client, pytest.raises(KaynakHatasi) as exc:
        kaynak_edin("https://github.com/ornek/proje", client=client)

    assert exc.value.kod == "yanit_gecersiz"


def test_mock_payload_json_serilestirilebilir(genel_ip: None) -> None:
    """Test fixture'ları yanlışlıkla özel nesne taşımıyor; frozen sidecar için koruma."""

    def _yanit(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(
                {
                    "id": 1,
                    "name": "proje",
                    "full_name": "ornek/proje",
                    "html_url": "https://github.com/ornek/proje",
                    "owner": {"login": "ornek"},
                }
            ).encode(),
        )

    with _istemci(_yanit) as client:
        belge = kaynak_edin("https://github.com/ornek/proje", client=client)

    json.dumps(belge.model_dump(mode="json"), ensure_ascii=False)

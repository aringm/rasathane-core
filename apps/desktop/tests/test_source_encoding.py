"""Kaynak byte'ları ve Türkçe analiz metni arasındaki kayıpsız sınır."""

from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from rasathane.sources import KaynakHatasi, kaynak_edin
from ytcore.content.node import ceviri_node
from ytcore.pipeline.api import kaynak_analiz_et

_FIXTURE = Path(__file__).parent / "fixtures" / "resmigazete-20261003-1.htm"
_RG_URL = "https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(*args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.delenv("RASATHANE_SOURCE_FIXTURE", raising=False)


def _source(raw: bytes, content_type: str = "text/html", url: str = _RG_URL) -> Any:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=raw, headers={"content-type": content_type})
        )
    ) as client:
        return kaynak_edin(url, client=client)


def test_resmigazete_actual_bytes_preserve_legal_terms_without_translation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _FIXTURE.read_bytes()
    receipt = json.loads(_FIXTURE.with_suffix(".json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
    assert receipt["content_type"] == "text/html"
    assert b"charset=Windows-1254" in raw
    document = _source(raw)
    assert "\ufffd" not in document.metin
    for term in ("Bağdaşmaz alan", "önlisans", "LÜY", "YEPDİS", "maden işletme ruhsatı"):
        assert term in document.metin
    for number in ("33389", "20/10/2015", "29508"):
        assert number in document.metin
    assert document.dil == "tr"
    assert document.ozel["encoding"] == "cp1254"
    assert document.ozel["encoding_source"] == "html_meta"
    assert document.ozel["language_source"] == "official_rg_content"
    assert document.ozel["source_bytes_sha256"] == receipt["sha256"]

    def forbidden_model(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Türkçe resmî kaynak yeniden LLM ile çevrilmemeli.")

    monkeypatch.setattr("ytcore.content.node.llm_al", forbidden_model)
    state = ceviri_node({"transkript_metni": document.metin, "transkript_kaynak_dil": document.dil})
    assert state["ceviri_durumu"] == "atlandi"
    assert state["icerik_tr"] == document.metin


@pytest.mark.parametrize(
    ("html", "content_type", "expected_encoding", "expected_source"),
    [
        (
            '<html lang="tr"><meta charset="windows-1254"><body>önlisans</body></html>',
            "text/html",
            "cp1254",
            "html_meta",
        ),
        (
            '<html lang="tr"><meta content="text/html; charset=windows-1254" '
            'http-equiv="CONTENT-TYPE"><body>önlisans</body></html>',
            "text/html",
            "cp1254",
            "html_meta",
        ),
        (
            '<html lang="tr"><meta charset="utf-8"><body>önlisans</body></html>',
            "text/html; charset=windows-1254",
            "cp1254",
            "http_charset",
        ),
    ],
)
def test_declared_encoding_precedence(
    html: str, content_type: str, expected_encoding: str, expected_source: str
) -> None:
    document = _source(html.encode("cp1254"), content_type, "https://example.com/legal")
    assert document.metin == "önlisans"
    assert document.dil == "tr"
    assert document.ozel["encoding"] == expected_encoding
    assert document.ozel["encoding_source"] == expected_source


def test_utf8_bom_wins_and_decodes_without_invented_characters() -> None:
    raw = '<html lang="tr"><body>önlisans</body></html>'.encode("utf-8-sig")
    document = _source(raw, "text/html; charset=windows-1254")
    assert document.metin == "önlisans"
    assert document.ozel["encoding_source"] == "bom"


@pytest.mark.parametrize(
    ("raw", "content_type"),
    [
        (b"<html><body>\xff broken</body></html>", "text/html"),
        (b"<html><body>plain</body></html>", "text/html; charset=unknown-encoding"),
        ("<html><body>bozuk \ufffd metin</body></html>".encode(), "text/html"),
        (b"<html><body>bozuk &#xfffd; metin</body></html>", "text/html"),
        (
            b'<html><meta charset="unknown-encoding"><body>plain</body></html>',
            "text/html",
        ),
    ],
)
def test_undecodable_or_replacement_content_fails_visibly(raw: bytes, content_type: str) -> None:
    with pytest.raises(KaynakHatasi) as error:
        _source(raw, content_type)
    assert error.value.kod == "kodlama_hatasi"
    assert "kodlama" in error.value.mesaj.lower() or "karakter" in error.value.mesaj.lower()


@pytest.mark.parametrize(
    ("html", "url", "expected_language"),
    [
        ('<html lang="en"><body>English source</body></html>', _RG_URL, "en"),
        (
            '<html><meta http-equiv="Content-Language" content="tr-TR">'
            "<body>Türkçe metin</body></html>",
            "https://example.com/legal",
            "tr",
        ),
        (
            "<html><body>Türkçe fakat dili bildirilmeyen metin</body></html>",
            "https://example.com/legal",
            None,
        ),
        ("<html><body>English source without declared language</body></html>", _RG_URL, None),
        (
            "<html><body>Resmî Gazete YÖNETMELİK MADDE 1.</body></html>",
            "https://fake-resmigazete.gov.tr/legal",
            None,
        ),
    ],
)
def test_language_routing_preserves_declarations_and_other_hosts(
    html: str, url: str, expected_language: str | None
) -> None:
    document = _source(html.encode(), url=url)
    assert document.dil == expected_language


def test_actual_rg_bytes_flow_through_pipeline_without_translation(
    tmp_output_base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _source(_FIXTURE.read_bytes())
    monkeypatch.setattr("rasathane.sources.kaynak_edin", lambda url: document)

    def forbidden_translation(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Türkçe kaynak için yeniden çeviri yasak.")

    monkeypatch.setattr("ytcore.content.node.cevir", forbidden_translation)
    result = kaynak_analiz_et(_RG_URL, "enerji", "rg-encoding-test", tmp_path / "checkpoints")
    assert result.transkript_durumu == "kaynak"
    assert result.index.anadil == "tr"
    assert result.ceviri_durumu == "atlandi"
    folder = Path(result.klasor)
    source = (folder / "01_kaynak-icerigi.md").read_text(encoding="utf-8")
    assert "\ufffd" not in source
    assert "Bağdaşmaz alan" in source and "LÜY" in source and "YEPDİS" in source
    assert not (folder / "02_transcript_tr.md").exists()
    provenance = result.quality_provenance
    assert provenance["source"]["encoding"] == "cp1254"
    assert provenance["source"]["translation_status"] == "atlandi"
    assert provenance["faithfulness"]["reference"] == "icerik_tr"
    assert provenance["faithfulness"]["independent_verification"] is False
    assert provenance["valuation"]["scope"] == "information_value_not_accuracy"
    summary = (folder / "04_ozet.md").read_text(encoding="utf-8")
    assert "Model destek tahmini" in summary
    assert "hukuki doğruluk onayı değildir" in summary


def test_encoding_error_pipeline_produces_error_receipt_without_generated_summary(
    tmp_output_base: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def invalid_source(url: str) -> Any:
        return _source(b"<html><body>\xff broken</body></html>")

    monkeypatch.setattr("rasathane.sources.kaynak_edin", invalid_source)
    result = kaynak_analiz_et(_RG_URL, "enerji", "rg-broken-test", tmp_path / "checkpoints")
    assert result.kaynak_durumu == "kodlama_hatasi"
    assert result.transkript_durumu == "hata"
    assert result.transkript_hata
    assert result.transkript_karakter == 0
    assert result.ozet_faithfulness is None
    assert not result.ozet_detay
    assert not (Path(result.klasor) / "04_ozet.md").exists()

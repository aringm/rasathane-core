from __future__ import annotations

import hashlib
import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import httpx
import pytest
from pypdf import PdfWriter, get_configuration
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    TextStringObject,
)
from rasathane import pdf_source, sources
from rasathane.sources import KaynakHatasi, KaynakTuru, kaynak_edin


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )


def pdf_bytes(pages=("Source evidence on page one.",), *, password=None, padding=0):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(("BT /F1 12 Tf 72 720 Td (" + escaped + ") Tj ET").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "Türkçe PDF başlığı", "/Author": "Örnek Yazar"})
    writer._root_object[NameObject("/Lang")] = TextStringObject("tr-TR")
    if padding:
        writer.add_attachment("padding.bin", b"x" * padding)
    if password:
        writer.encrypt(password)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def fetch(data, mime="application/pdf", *, content_length=None):
    headers = {"content-type": mime} if mime else {}
    if content_length is not None:
        headers["content-length"] = str(content_length)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=data, headers=headers)
        )
    ) as client:
        return kaynak_edin("https://example.org/document.pdf#page=2", client=client)


@pytest.mark.parametrize(
    "mime",
    [
        "application/pdf",
        "application/pdf; charset=binary",
        "application/octet-stream",
        "",
        "text/html",
    ],
)
def test_pdf_magic_metadata_and_page_receipts(mime):
    data = pdf_bytes(("First source evidence.", "Second source evidence."))
    result = fetch(data, mime)
    assert result.tur is KaynakTuru.web
    assert result.baslik == "Türkçe PDF başlığı" and result.sahip == "Örnek Yazar"
    assert result.dil == "tr" and result.edinim_durumu == "tam"
    assert result.metin == "First source evidence.\n\nSecond source evidence."
    assert result.kanonik_url == "https://example.org/document.pdf"
    assert result.ozel["page_count"] == result.ozel["text_page_count"] == 2
    assert result.ozel["text_pages"] == [1, 2]
    assert result.ozel["full_text_extracted"] is True
    assert result.ozel["ocr_performed"] is False
    assert result.ozel["source_bytes_sha256"] == hashlib.sha256(data).hexdigest()
    for page in result.ozel["pdf_pages"]:
        text = result.metin[page["start"] : page["end"]]
        assert hashlib.sha256(text.encode()).hexdigest() == page["text_sha256"]
    assert result.ozel["original_text_sha256"] == hashlib.sha256(result.metin.encode()).hexdigest()


@pytest.mark.parametrize(
    "data", [b"<html>not a PDF</html>", b"%PDF-1.7\ncorrupt\n%%EOF", b"%PDF-1.7\ntruncated"]
)
def test_declared_or_malformed_pdf_never_falls_back_to_html(data):
    with pytest.raises(KaynakHatasi) as error:
        fetch(data)
    assert error.value.kod == "pdf_gecersiz"


def test_binary_without_pdf_magic_rejected():
    with pytest.raises(KaynakHatasi) as error:
        fetch(b"PK\x03\x04not-a-pdf", "application/octet-stream")
    assert error.value.kod == "desteklenmeyen_icerik"


def test_pdf_password_and_missing_text_have_typed_errors():
    for data, expected in (
        (pdf_bytes(password="fixture-password"), "pdf_sifreli"),
        (pdf_bytes(("",)), "pdf_metin_yok"),
    ):
        with pytest.raises(KaynakHatasi) as error:
            fetch(data)
        assert error.value.kod == expected


def test_mixed_empty_pages_are_truthfully_partial():
    result = fetch(pdf_bytes(("Visible source text.", "")))
    assert result.edinim_durumu == "kismi"
    assert result.ozel["full_text_extracted"] is False
    assert result.ozel["pdf_pages_without_text"] == [2]
    assert "pages_without_text" in result.ozel["truncation_reasons"]
    assert "kısmi" in result.ozel["notice"]


def test_page_and_character_limits_keep_explicit_partial_scope(monkeypatch):
    data = pdf_bytes(("First source evidence.", "Second source evidence."))
    monkeypatch.setattr(pdf_source, "MAX_PAGES", 1)
    result = fetch(data)
    assert result.ozel["page_count"] == 2 and result.ozel["text_page_count"] == 1
    assert result.edinim_durumu == "kismi" and "page_limit" in result.ozel["truncation_reasons"]
    monkeypatch.setattr(pdf_source, "MAX_PAGES", 200)
    monkeypatch.setattr(pdf_source, "MAX_CHARS", 10)
    result = fetch(data)
    assert len(result.metin) == 10
    assert not result.ozel["full_text_extracted"]
    assert "character_limit" in result.ozel["truncation_reasons"]


def test_pdf_stream_budget_and_configuration_are_scoped(monkeypatch):
    before = get_configuration()
    monkeypatch.setattr(pdf_source, "MAX_PAGE_STREAM_BYTES", 20)
    with pytest.raises(KaynakHatasi) as error:
        fetch(pdf_bytes())
    assert error.value.kod == "pdf_limit"
    assert get_configuration() is before


def test_only_pdf_magic_gets_larger_download_budget(monkeypatch):
    monkeypatch.setattr(sources, "_MAKSIMUM_YANIT_BYTE", 1000)
    monkeypatch.setattr(sources, "_MAKSIMUM_PDF_BYTE", 5000)
    data = pdf_bytes(padding=1500)
    assert 1000 < len(data) < 5000
    assert fetch(data, "application/octet-stream").ozel["full_text_extracted"]
    for mime in ("text/html", "application/pdf", "application/octet-stream"):
        with pytest.raises(KaynakHatasi) as error:
            fetch(b"<html>" + b"x" * 1500, mime)
        assert error.value.kod == "yanit_cok_buyuk"
    with pytest.raises(KaynakHatasi) as error:
        fetch(data, content_length=6000)
    assert error.value.kod == "yanit_cok_buyuk"
    with pytest.raises(KaynakHatasi) as error:
        fetch(pdf_bytes(padding=5500))
    assert error.value.kod == "yanit_cok_buyuk"


def test_pdf_redirect_does_not_relax_existing_ssrf_policy():
    calls = []

    def reply(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/internal.pdf"})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(KaynakHatasi) as error:
            kaynak_edin("https://example.org/document.pdf", client=client)
    assert error.value.kod == "yonlendirme_engellendi" and len(calls) == 1


def test_warning_receipts_do_not_mix_threads_or_leak_handlers():
    logger = logging.getLogger("pypdf")
    before = list(logger.handlers)

    barrier = threading.Barrier(2)

    def work(name):
        with pdf_source._parser_warnings() as warnings:
            barrier.wait(timeout=5)
            logging.getLogger("pypdf._page").warning(name)
            barrier.wait(timeout=5)
        return warnings

    with ThreadPoolExecutor(max_workers=2) as executor:
        result = list(executor.map(work, ["warning-one", "warning-two"]))
    assert result == [["warning-one"], ["warning-two"]]
    assert logger.handlers == before


def form_pdf(repeats=500, form_text="Normal source sentence."):
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    fonts = DictionaryObject({NameObject("/F1"): writer._add_object(font)})
    forms = DictionaryObject()
    for name, text in (("/Fm", form_text), ("/Last", "LAST_EVIDENCE_IS_REQUIRED")):
        form = DecodedStreamObject()
        form.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([FloatObject(n) for n in (0, 0, 200, 200)]),
                NameObject("/Resources"): DictionaryObject({NameObject("/Font"): fonts}),
            }
        )
        form.set_data(("BT /F1 12 Tf 10 10 Td (" + text + ") Tj ET").encode())
        forms[NameObject(name)] = writer._add_object(form)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): forms})
    stream = DecodedStreamObject()
    stream.set_data(b"/Fm Do\n" * repeats + b"/Last Do\n")
    page[NameObject("/Contents")] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pypdf_silent_xform_limit_never_claims_complete_extraction():
    result = fetch(form_pdf())
    assert "LAST_EVIDENCE_IS_REQUIRED" not in result.metin
    assert result.edinim_durumu == "kismi" and result.ozel["full_text_extracted"] is False
    assert "parser_warnings" in result.ozel["truncation_reasons"]
    assert any(
        "form XObject invocations" in warning for warning in result.ozel["pdf_parser_warnings"]
    )


@pytest.mark.parametrize("limit", ["text", "operations", "time"])
def test_nested_forms_abort_before_unbounded_output_and_restore_receipt_handler(monkeypatch, limit):
    if limit == "text":
        monkeypatch.setattr(pdf_source, "MAX_EXTRACTED_CHARS", 50)
    elif limit == "operations":
        monkeypatch.setattr(pdf_source, "MAX_OPERATIONS", 10)
    else:
        calls = 0

        def clock():
            nonlocal calls
            calls += 1
            return 0.0 if calls <= 2 else 100.0

        monkeypatch.setattr(pdf_source.time, "monotonic", clock)
    logger = logging.getLogger("pypdf")
    before = list(logger.handlers)
    config = get_configuration()
    with pytest.raises(KaynakHatasi) as error:
        fetch(form_pdf(repeats=10))
    assert error.value.kod == "pdf_limit"
    assert logger.handlers == before
    assert get_configuration() is config

from __future__ import annotations

import hashlib
import json
import socket
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, TextStringObject
from rasathane import sources
from ytcore.pipeline.api import kaynak_analiz_et


def _document(blank_page: bool) -> bytes:
    writer = PdfWriter()
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
    content = DecodedStreamObject()
    content.set_data(
        b"BT /F1 12 Tf 72 720 Td (Independent source evidence. "
        b"Page coverage must be preserved.) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    if blank_page:
        writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": "PDF source coverage"})
    writer._root_object[NameObject("/Lang")] = TextStringObject("tr")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("blank_page", [False, True])
def test_pdf_bytes_reach_saved_pipeline_scope(
    tmp_output_base: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    blank_page: bool,
) -> None:
    data = _document(blank_page)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    original_fetch = sources.kaynak_edin
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=data, headers={"content-type": "application/pdf"}
            )
        )
    ) as client:
        monkeypatch.setattr(sources, "kaynak_edin", lambda url: original_fetch(url, client=client))
        result = kaynak_analiz_et(
            "https://example.org/source.pdf",
            "genel",
            f"pdf-pipeline-{blank_page}",
            tmp_path / "checkpoints",
        )
    assert result.stub is False and result.kaynak_turu == "web"
    assert result.kaynak_durumu == ("kismi" if blank_page else "tam")
    assert result.ceviri_durumu == "atlandi"
    provenance = result.quality_provenance["source"]
    assert provenance["source_format"] == "pdf"
    assert provenance["bytes_sha256"] == hashlib.sha256(data).hexdigest()
    assert provenance["page_count"] == (2 if blank_page else 1)
    assert provenance["text_page_count"] == 1
    assert provenance["text_pages"] == [1]
    assert provenance["full_text_extracted"] is (not blank_page)
    assert provenance["ocr_performed"] is False
    assert provenance["text_scope"] == "pdf_text_layer"
    folder = Path(result.klasor)
    index = json.loads((folder / "00_index.json").read_text(encoding="utf-8"))
    assert index["kaynak_ozel"]["source_format"] == "pdf"
    assert index["kaynak_ozel"]["text_pages"] == [1]
    for filename in ("01_kaynak-icerigi.md", "04_ozet.md"):
        saved = (folder / filename).read_text(encoding="utf-8")
        assert f"1/{provenance['page_count']} sayfada metin katmanı okundu" in saved
        assert provenance["notice"] in saved
        if blank_page:
            assert "kısmi" in saved
    raw = (folder / "01_kaynak-icerigi.md").read_text(encoding="utf-8")
    assert "Independent source evidence." in raw
    assert result.ozet_detay

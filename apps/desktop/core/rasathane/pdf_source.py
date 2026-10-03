"""Metin katmanı bulunan PDF için sınırlı, yerel kaynak edinimi; OCR çalıştırmaz."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import pypdf
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError
from pypdf.generic import DictionaryObject

from rasathane.sources import KaynakBelgesi, KaynakHatasi, KaynakSinyali, KaynakTuru

MAX_PAGES = 200
MAX_CHARS = 500_000
MAX_PAGE_STREAM_BYTES = 5_000_000
MAX_TOTAL_STREAM_BYTES = 20_000_000
MAX_SECONDS = 30.0
MAX_OPERATIONS = 500_000
MAX_EXTRACTED_CHARS = 1_000_000


class _ExtractionBudgetExceeded(BaseException):
    """Bypass pypdf's recover-and-skip Exception handlers; caught only here."""


@contextmanager
def _parser_warnings() -> Iterator[list[str]]:
    messages: list[str] = []
    thread_id = threading.get_ident()

    class Receipt(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.thread == thread_id and record.levelno >= logging.WARNING:
                if len(messages) < 20:
                    messages.append(" ".join(record.getMessage().split())[:300])

    logger = logging.getLogger("pypdf")
    handler = Receipt(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        yield messages
    finally:
        logger.removeHandler(handler)


def _clean(value: Any, limit: int = 1000) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.replace("\x00", "").split())[:limit]
    return text or None


def pdf_belgesi(url: str, content: bytes, content_type: str) -> KaynakBelgesi:
    if not content.lstrip().startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
        raise KaynakHatasi("pdf_gecersiz", "Kaynak geçerli, eksiksiz bir PDF döndürmedi.")
    deadline = time.monotonic() + MAX_SECONDS
    parts: list[str] = []
    page_receipts: list[dict[str, Any]] = []
    empty_pages: list[int] = []
    chars = stream_bytes = 0
    reasons: list[str] = []
    operation_count = extracted_chars = 0

    def before_operand(*args: Any) -> None:
        nonlocal operation_count
        operation_count += 1
        if operation_count > MAX_OPERATIONS or time.monotonic() > deadline:
            raise _ExtractionBudgetExceeded

    def visit_text(fragment: str, *args: Any) -> None:
        nonlocal extracted_chars
        extracted_chars += len(fragment)
        if extracted_chars > MAX_EXTRACTED_CHARS or time.monotonic() > deadline:
            raise _ExtractionBudgetExceeded

    try:
        # Public configuration is scoped to this execution context, never global.
        # No renderer, image decompressor subprocess, JavaScript or OCR is invoked.
        with (
            _parser_warnings() as warnings,
            apply_configuration(
                maximum_declared_stream_length=MAX_PAGE_STREAM_BYTES,
                array_based_stream_maximum_output_length=MAX_PAGE_STREAM_BYTES,
                zlib_maximum_output_length=MAX_PAGE_STREAM_BYTES,
                zlib_maximum_recovery_input_length=1_000_000,
                lzw_maximum_output_length=MAX_PAGE_STREAM_BYTES,
                run_length_maximum_output_length=MAX_PAGE_STREAM_BYTES,
                image_maximum_buffer_size=MAX_PAGE_STREAM_BYTES,
                jbig2_maximum_output_length=MAX_PAGE_STREAM_BYTES,
                jbig2dec_binary=None,
                page_tree_maximum_entries=1000,
                page_tree_maximum_depth=30,
                xform_maximum_invocations_per_extraction=500,
            ),
        ):
            reader = PdfReader(BytesIO(content), strict=False, root_object_recovery_limit=1000)
            if reader.is_encrypted:
                raise KaynakHatasi(
                    "pdf_sifreli",
                    "Parola korumalı PDF desteklenmiyor; korumasız metinli sürümü kullanın.",
                )
            total_pages = len(reader.pages)
            if total_pages == 0:
                raise KaynakHatasi("pdf_metin_yok", "PDF içinde okunabilir sayfa bulunamadı.")
            metadata = reader.metadata
            title = _clean(metadata.title if metadata else None)
            author = _clean(metadata.author if metadata else None)
            pdf_metadata = {
                "title": title,
                "author": author,
                "subject": _clean(metadata.subject if metadata else None),
                "creator": _clean(metadata.creator if metadata else None),
                "producer": _clean(metadata.producer if metadata else None),
                "creation_date_raw": _clean(metadata.get("/CreationDate") if metadata else None),
                "modification_date_raw": _clean(metadata.get("/ModDate") if metadata else None),
            }
            root = reader.trailer["/Root"]
            language = _clean(root.get("/Lang") if isinstance(root, DictionaryObject) else None, 30)
            if not language or not re.fullmatch(
                r"[a-zA-Z]{2,3}(?:[-_][a-zA-Z0-9]{2,8})*", language
            ):
                language = None
            processed_pages = 0
            for index in range(min(total_pages, MAX_PAGES)):
                if time.monotonic() > deadline:
                    reasons.append("time_limit")
                    break
                page = reader.pages[index]
                contents = page.get_contents()
                page_bytes = len(contents.get_data()) if contents is not None else 0
                if stream_bytes + page_bytes > MAX_TOTAL_STREAM_BYTES:
                    reasons.append("stream_budget")
                    break
                stream_bytes += page_bytes
                raw = (
                    page.extract_text(
                        visitor_operand_before=before_operand, visitor_text=visit_text
                    )
                    or ""
                )
                if "\ufffd" in raw:
                    raise KaynakHatasi(
                        "kodlama_hatasi", "PDF metninde bozulmuş karakterler bulundu."
                    )
                text = " ".join(raw.replace("\x00", "").split())
                processed_pages += 1
                if not text:
                    empty_pages.append(index + 1)
                    continue
                separator = 2 if parts else 0
                remaining = MAX_CHARS - chars - separator
                if len(text) > remaining:
                    text = text[: max(0, remaining)]
                    reasons.append("character_limit")
                if text:
                    start = chars + separator
                    parts.append(text)
                    chars = start + len(text)
                    page_receipts.append(
                        {
                            "page": index + 1,
                            "start": start,
                            "end": chars,
                            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        }
                    )
                if time.monotonic() > deadline:
                    reasons.append("time_limit")
                if reasons:
                    break
            if total_pages > MAX_PAGES:
                reasons.append("page_limit")
    except _ExtractionBudgetExceeded as exc:
        raise KaynakHatasi(
            "pdf_limit", "PDF metin çözümleme süre veya işlem sınırını aşıyor."
        ) from exc
    except KaynakHatasi:
        raise
    except LimitReachedError as exc:
        raise KaynakHatasi("pdf_limit", "PDF çözümleme kaynak sınırını aşıyor.") from exc
    except Exception as exc:
        raise KaynakHatasi(
            "pdf_gecersiz", "PDF metni güvenle okunamadı; dosya bozuk olabilir."
        ) from exc
    if not parts:
        if reasons:
            raise KaynakHatasi("pdf_limit", "PDF metni kaynak sınırları içinde okunamadı.")
        raise KaynakHatasi(
            "pdf_metin_yok", "PDF metin katmanı içermiyor; taranmış sayfalar için OCR gerekli."
        )
    if warnings:
        reasons.append("parser_warnings")
    if empty_pages:
        reasons.append("pages_without_text")
    text = "\n\n".join(parts)
    parsed = urlsplit(url)
    canonical = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    title = title or _clean(unquote(parsed.path.rsplit("/", 1)[-1])) or "PDF belgesi"
    return KaynakBelgesi(
        tur=KaynakTuru.web,
        kimlik=hashlib.sha256(canonical.encode()).hexdigest()[:20],
        kanonik_url=canonical,
        baslik=title,
        sahip=author,
        dil=re.split(r"[-_]", language, maxsplit=1)[0].lower() if language else None,
        metin=text,
        metrikler={
            "sayfa_sayisi": total_pages,
            "karakter_sayisi": len(text),
            "kelime_sayisi": len(text.split()),
        },
        ozel={
            "format": "pdf",
            "source_format": "pdf",
            "page_count": total_pages,
            "text_page_count": len(page_receipts),
            "text_pages": [item["page"] for item in page_receipts],
            "extraction_method": "pypdf_text_layer",
            "original_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "notice": (
                f"PDF metin katmanı kısmi okundu: {len(page_receipts)}/{total_pages} "
                f"sayfada metin alındı. Kapsam sınırları: {', '.join(reasons)}. OCR yapılmadı."
                if reasons
                else "PDF metin katmanı okundu. Görseller, tablo düzeni ve OCR doğrulanmadı."
            ),
            "content_type": content_type or None,
            "source_bytes_sha256": hashlib.sha256(content).hexdigest(),
            "source_bytes": len(content),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "extractor": "pypdf",
            "extractor_version": pypdf.__version__,
            "text_scope": "pdf_text_layer",
            "full_text_fetched": True,
            "full_text_extracted": not reasons,
            "ocr_performed": False,
            "language_source": "pdf_catalog" if language else "unknown",
            "pdf_metadata": pdf_metadata,
            "pdf_parser_warnings": warnings,
            "pdf_pages": page_receipts,
            "pdf_total_pages": total_pages,
            "pdf_processed_pages": processed_pages,
            "pdf_pages_without_text": empty_pages,
            "truncation_reasons": reasons,
            "limits": {
                "max_pages": MAX_PAGES,
                "max_chars": MAX_CHARS,
                "max_page_stream_bytes": MAX_PAGE_STREAM_BYTES,
                "max_total_page_stream_bytes": MAX_TOTAL_STREAM_BYTES,
                "max_operations": MAX_OPERATIONS,
                "max_extracted_chars": MAX_EXTRACTED_CHARS,
            },
        },
        sinyaller=[
            KaynakSinyali(
                etiket="pdf_metin_kapsami",
                deger="partial" if reasons else "text_layer",
                aciklama=(
                    "PDF metin katmanı okundu; görsel, tablo düzeni veya OCR doğrulaması yapılmadı."
                ),
                durum="uyari" if reasons else "bilgi",
            )
        ],
        edinim_durumu="kismi" if reasons else "tam",
    )

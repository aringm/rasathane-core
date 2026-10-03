import assert from "node:assert/strict";
import test from "node:test";
import { sourceFormatDetails } from "../src/source-format.js";

const source = { source_format: "pdf", page_count: 5, text_page_count: 5, full_text_extracted: true, ocr_performed: false, extraction_method: "pypdf_text_layer", bytes_sha256: "a".repeat(64) };
test("PDF metadata clearly limits analysis to the text layer even when all pages contain text", () => {
  const details = sourceFormatDetails({ quality_provenance: { source } });
  assert.equal(details.label, "PDF (Web)");
  assert.equal(details.partial, false);
  assert.equal(details.bytesSha256, source.bytes_sha256);
  assert.match(details.description, /5\/5 sayfada metin/);
  assert.match(details.description, /OCR yapılmadı/);
  assert.match(details.description, /Görseller, tablo düzeni ve taranmış içerik değerlendirilmedi/);
});
test("mixed scanned and text pages show a partial scope rather than a complete PDF analysis", () => {
  const details = sourceFormatDetails({ index: { kaynak_ozel: { ...source, text_page_count: 2, full_text_extracted: false, truncation_reasons: ["pages_without_text"] } } });
  assert.equal(details.partial, true);
  assert.match(details.description, /Kısmi PDF metni/);
  assert.match(details.description, /2\/5 sayfada metin/);
  assert.match(details.description, /Bazı sayfalarda metin katmanı bulunamadı/);
});
test("unknown PDF warnings become bounded plain text and provenance readback wins over the index", () => {
  const details = sourceFormatDetails({ index: { kaynak_ozel: source }, quality_provenance: { source: { ...source, text_page_count: 3, truncation_reasons: ["<script>untrusted</script>"] } } });
  assert.equal(details.textPages, 3);
  assert.match(details.description, /çözümleme sınırı/);
  assert.equal(details.description.includes("<script>"), false);
});
test("a PDF-looking URL without an extracted PDF receipt remains an ordinary web source", () => {
  assert.equal(sourceFormatDetails({ index: { kaynak_url: "https://example.com/report.pdf" } }), null);
  assert.equal(sourceFormatDetails({ quality_provenance: { source: { source_format: "html" } } }), null);
});

"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { conservativeSearchClaims } = require("./smoke-evidence.cjs");

function claim(overrides = {}) {
  return { karar: "BELİRSİZ", guven: 0, bagimsiz_dogrulama: false,
    kanit_turu: "arama_ozeti", kaynaklar: ["https://example.org/source"],
    ilgili_kaynaklar: [], aday_karar: null, gerekce: "Arama özeti bağımsız doğrulama değildir.", ...overrides };
}
function absent(overrides = {}) {
  return claim({ kanit_turu: "yok", kaynaklar: [],
    gerekce: "Web doğrulaması yapılamadı (kaynak yok).", ...overrides });
}

test("arama bulunamayan iddia belirsiz kaldığında gerçek analiz kabul edilir", () => {
  assert.equal(conservativeSearchClaims([claim(), absent()]), true);
});
test("kaynak yokken kanıt veya aday karar üretildiği iddiası reddedilir", () => {
  for (const overrides of [
    { kaynaklar: ["https://example.org/source"] },
    { ilgili_kaynaklar: ["https://example.org/source"] },
    { aday_karar: "DESTEKLİYOR" }, { gerekce: "" }, { kaynaklar: null },
  ]) assert.equal(conservativeSearchClaims([absent(overrides)]), false);
});
test("snippet veya boş arama bağımsız doğrulama ve kesin karar sayılmaz", () => {
  for (const make of [claim, absent]) {
    for (const overrides of [{ karar: "DESTEKLİYOR" }, { guven: 0.8 },
      { bagimsiz_dogrulama: true }, { bagimsiz_dogrulama: undefined }]) {
      assert.equal(conservativeSearchClaims([make(overrides)]), false);
    }
  }
});
test("iddia listesi ve arama kanıtının açık olması gerekir", () => {
  for (const value of [null, [], [null], [{}], [claim({ kanit_turu: "tam_metin" })],
    [claim({ kaynaklar: [] })]]) assert.equal(conservativeSearchClaims(value), false);
});

const { pdfAcceptanceReceipt } = require("./smoke-product-ui.cjs");
function pdfJob(overrides = {}) {
  const source = { source_format: "pdf", text_scope: "pdf_text_layer", extraction_method: "pypdf_text_layer", page_count: 2, text_page_count: 2, ocr_performed: false, full_text_extracted: true, bytes_sha256: "a".repeat(64), original_text_sha256: "b".repeat(64), ...overrides };
  return { id: "saved-pdf-job", status: "completed", request: { url: "https://example.com/paper.pdf" }, result: {
    stub: false, kaynak_turu: "web", motor: { backend: "llamacpp" }, cloud_cagrisi_sayisi: 0,
    index: { kaynak_ozel: { source_format: "pdf", page_count: 2 } },
    quality_provenance: { source }, ozet_detay: "Kaynak metninden oluşturulan özet.",
    artifacts: [{ bytes: 100, sha256: "c".repeat(64) }],
  } };
}
test("PDF native acceptance requires the saved source hash, local model and actual output receipt", () => {
  const job = pdfJob();
  const receipt = pdfAcceptanceReceipt(job, job.request.url);
  assert.equal(receipt.pages, 2);
  assert.equal(receipt.partial, false);
  for (const invalid of [
    { ...job, status: "failed" },
    { ...job, result: { ...job.result, artifacts: [] } },
    { ...job, result: { ...job.result, stub: true } },
    { ...job, result: { ...job.result, motor: { backend: "cloud" } } },
    pdfJob({ bytes_sha256: "unverified" }), pdfJob({ text_page_count: 0 }),
    pdfJob({ source_format: "html" }), pdfJob({ ocr_performed: true }),
  ]) assert.throws(() => pdfAcceptanceReceipt(invalid, job.request.url), /doğrulanamadı/);
  assert.throws(() => pdfAcceptanceReceipt(job, "https://example.com/other.pdf"), /doğrulanamadı/);
});
test("PDF native acceptance preserves partial extraction instead of silently claiming every page was read", () => {
  const missing = pdfJob({ text_page_count: 1, full_text_extracted: false, truncation_reasons: ["pages_without_text"] });
  assert.throws(() => pdfAcceptanceReceipt(missing, missing.request.url), /uyarısı eksik/);
  const partial = pdfJob({ text_page_count: 1, full_text_extracted: false, truncation_reasons: ["pages_without_text"], notice: "Kısmi PDF metni. OCR yapılmadı." });
  assert.equal(pdfAcceptanceReceipt(partial, partial.request.url).partial, true);
});

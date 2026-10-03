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

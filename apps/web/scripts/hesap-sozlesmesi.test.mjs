import assert from "node:assert/strict";
import { test } from "node:test";
import { indirmeUrl, publicUrunOku, urunSozlesmesi, RASATHANE_URUN_URL } from "../src/lib/rasathane-hesap.ts";

const product = { schema_version: "1.0", product: "rasathane", released: true, currency: "TRY", monthly_total_kurus: 4900, tax_included: true, recurring: false, trial_days: 14, platforms: [{ platform: "win", available: true, version: "1.0.0", sha256: "a".repeat(64), size: "150 MB" }, { platform: "mac", available: false, version: null, sha256: null, size: null }] };
test("doğrulanmış metadata gerçek Rasathane indirme adresine bağlanır; yanıt URL'i kullanılmaz", () => {
  assert.deepEqual(urunSozlesmesi({ ...product, downloadUrl: "https://other.example/paket.exe" }), product);
  assert.equal(indirmeUrl("win"), "https://www.muhakeme.ai/api/download?urun=rasathane&platform=win");
  assert.throws(() => indirmeUrl("other"));
});
test("yanlış ürün, fiyat, eksik hash ve yayımlanmamış paketi reddeder", () => {
  assert.equal(urunSozlesmesi({ ...product, product: "uyap" }), null);
  assert.equal(urunSozlesmesi({ ...product, monthly_total_kurus: 5880 }), null);
  assert.equal(urunSozlesmesi({ ...product, released: false }), null);
  assert.equal(urunSozlesmesi({ ...product, platforms: [{ ...product.platforms[0], sha256: null }, product.platforms[1]] }), null);
  assert.equal(urunSozlesmesi({ ...product, platforms: [product.platforms[0], product.platforms[0]] }), null);
});
test("public discovery sabit HTTPS origin ve no-store kullanır; ağ veya schema hatasında bağlantı verilmez", async () => {
  const parsed = await publicUrunOku(async (url, init) => {
    assert.equal(url, RASATHANE_URUN_URL);
    assert.equal(init.redirect, "error");
    assert.equal(init.cache, "no-store");
    return Response.json(product);
  });
  assert.deepEqual(parsed, product);
  assert.equal(await publicUrunOku(async () => new Response("", { status: 404 })), null);
  assert.equal(await publicUrunOku(async () => { throw new Error("offline"); }), null);
});

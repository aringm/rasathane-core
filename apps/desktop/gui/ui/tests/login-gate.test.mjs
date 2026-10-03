import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { createLoginGate } from "../src/login-gate.js";

function deferred() {
  let resolve; let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fixture(t, pending, native = true, methods = {}) {
  const previous = { window: globalThis.window, document: globalThis.document };
  const nodes = new Map(); const classes = new Set(["session-locked"]);
  const node = () => ({ hidden: false, inert: false, value: "", attributes: {}, listeners: {}, setAttribute(k, v) { this.attributes[k] = v; }, addEventListener(k, fn) { this.listeners[k] = fn; }, focus() { this.focused = !this.disabled; } });
  const surfaces = [node(), node(), node(), node()];
  let onAccountChange; let unlocked = 0; let locked = 0;
  globalThis.document = { body: { classList: { toggle: (key, value) => value ? classes.add(key) : classes.delete(key) } }, querySelectorAll: selector => selector === "dialog[open]" ? [] : surfaces };
  globalThis.window = { addEventListener() {}, rasathane: native ? { accountStatus: () => pending.promise, onAccountChange: fn => { onAccountChange = fn; return () => {}; }, ...methods } : undefined };
  t.mock.method(globalThis, "setTimeout", () => 1);
  t.mock.method(globalThis, "clearTimeout", () => {});
  t.after(() => { for (const key of ["window", "document"]) if (previous[key] === undefined) delete globalThis[key]; else globalThis[key] = previous[key]; });
  const gate = createLoginGate({ $: id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id); }, onUnlock: () => { unlocked++; }, onLock: () => { locked++; } });
  return { gate, nodes, surfaces, classes, event: value => onAccountChange(value), counts: () => ({ unlocked, locked }) };
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test("HTML ve ilk hesap kontrolü sonuçlanana kadar bütün ürün yüzeyleri kilitlidir", async t => {
  const html = fs.readFileSync(new URL("../index.html", import.meta.url), "utf8");
  assert.match(html, /<body[^>]*class="[^"]*session-locked/);
  const pending = deferred(); const h = fixture(t, pending);
  assert.equal(h.gate.allowed(), false);
  assert.equal(h.nodes.get("giris-ekrani").hidden, false);
  assert.ok(h.surfaces.every(item => item.inert && item.attributes["aria-hidden"] === "true"));
  pending.reject(new Error("network unavailable")); await settle();
  assert.equal(h.gate.allowed(), false);
  assert.deepEqual(h.counts(), { unlocked: 0, locked: 0 });
});

const login = () => ({ email: "ornek@example.com", expiresAt: new Date(Date.now() + 600000).toISOString(), resendAt: new Date(Date.now() + 60000).toISOString() });
const submit = (h, id) => h.nodes.get(id).listeners.submit({ preventDefault() {} });

test("e-posta → yanlış kod → doğru kod: yalnız doğrulanmış oturum ekranları açar ve kod temizlenir", async t => {
  const pending = deferred(); let verifies = 0; let sends = 0;
  const h = fixture(t, pending, true, {
    sendLoginCode: async email => { sends++; assert.equal(email, "ornek@example.com"); return { state: "code_sent", login: login() }; },
    verifyLoginCode: async value => { assert.equal(value, verifies ? "123456" : "000000"); return ++verifies === 1 ? { state: "code_sent", errorCode: "wrong_code", login: login() } : { state: "signed_in" }; },
  });
  pending.resolve({ state: "signed_out" }); await settle();
  h.nodes.get("giris-email").value = "ornek@example.com";
  await submit(h, "giris-email-form");
  assert.equal(h.nodes.get("giris-kod-form").hidden, false);
  assert.equal(h.nodes.get("giris-kod").focused, true);
  assert.equal(h.nodes.get("giris-tekrar").disabled, true);
  await h.nodes.get("giris-tekrar").listeners.click(); assert.equal(sends, 1);
  assert.equal(h.gate.allowed(), false); assert.ok(h.surfaces.every(item => item.inert));
  h.nodes.get("giris-kod").value = "000000"; await submit(h, "giris-kod-form");
  assert.match(h.nodes.get("giris-durum").textContent, /Kod yanlış/);
  assert.equal(h.nodes.get("giris-dogrula").disabled, false); assert.equal(h.gate.allowed(), false);
  h.nodes.get("giris-kod").value = "123456"; await submit(h, "giris-kod-form");
  assert.equal(h.gate.allowed(), true); assert.ok(h.surfaces.every(item => !item.inert));
  assert.equal(h.nodes.get("giris-kod").value, ""); assert.equal(h.nodes.get("giris-email").value, "");
  assert.deepEqual(h.counts(), { unlocked: 1, locked: 0 });
});

test("e-posta değiştirme geciken verify yanıtını reddeder ve yeni giriş için alanı açar", async t => {
  const pending = deferred(); const verification = deferred();
  const h = fixture(t, pending, true, {
    sendLoginCode: async () => ({ state: "code_sent", login: login() }),
    verifyLoginCode: () => verification.promise,
    cancelLogin: async () => ({ state: "signed_out" }),
  });
  pending.resolve({ state: "signed_out" }); await settle();
  h.nodes.get("giris-email").value = "ornek@example.com"; await submit(h, "giris-email-form");
  h.nodes.get("giris-kod").value = "123456"; const verifying = submit(h, "giris-kod-form");
  assert.equal(h.nodes.get("giris-iptal").hidden, false);
  await h.nodes.get("giris-degistir").listeners.click();
  verification.resolve({ state: "signed_in" }); await verifying;
  assert.equal(h.gate.allowed(), false); assert.equal(h.nodes.get("giris-email-form").hidden, false);
  assert.equal(h.nodes.get("giris-email").disabled, false); assert.equal(h.nodes.get("giris-kod").value, "");
});

test("süresi dolmuş kod doğrulanamaz; resend yeniden kullanılabilir ve yasal belgeler sabit seçim gönderir", async t => {
  const pending = deferred(); let document; let sends = 0;
  const h = fixture(t, pending, true, {
    sendLoginCode: async () => { sends++; return { state: "code_sent", login: login() }; },
    verifyLoginCode: async () => { throw new Error("expired code must not submit"); },
    openLoginDocument: async value => { document = value; },
  });
  pending.resolve({ state: "signed_out" }); await settle();
  h.event({ state: "failed", errorCode: "expired_code", login: { ...login(), expiresAt: new Date(Date.now() - 1000).toISOString(), resendAt: new Date(Date.now() - 1000).toISOString() } });
  assert.equal(h.nodes.get("giris-dogrula").disabled, true); await submit(h, "giris-kod-form");
  assert.equal(h.nodes.get("giris-tekrar").disabled, false); await h.nodes.get("giris-tekrar").listeners.click(); assert.equal(sends, 1);
  await h.nodes.get("giris-kosullar").listeners.click(); assert.equal(document, "terms");
  await h.nodes.get("giris-kvkk").listeners.click(); assert.equal(document, "privacy");
  assert.equal(h.gate.allowed(), false);
});

test("daha yeni native olay eski gönderim yanıtından üstün tutulur", async t => {
  const pending = deferred(); const sending = deferred();
  const h = fixture(t, pending, true, { sendLoginCode: () => sending.promise, verifyLoginCode: async () => ({ state: "signed_in" }) });
  pending.resolve({ state: "signed_out" }); await settle();
  h.nodes.get("giris-email").value = "ornek@example.com"; const request = submit(h, "giris-email-form");
  h.event({ state: "code_sent", login: login() }); h.event({ state: "signed_out" });
  sending.resolve({ state: "code_sent", login: login() }); await request;
  assert.equal(h.gate.allowed(), false); assert.equal(h.nodes.get("giris-kod-form").hidden, true);
});

test("eski accountStatus signed_in yanıtı daha yeni çıkış olayını geri alamaz", async t => {
  const pending = deferred(); const h = fixture(t, pending);
  h.event({ state: "signed_in" });
  assert.equal(h.gate.allowed(), true);
  h.event({ state: "signed_out" });
  pending.resolve({ state: "signed_in" }); await settle();
  assert.equal(h.gate.allowed(), false);
  assert.equal(h.nodes.get("giris-ekrani").hidden, false);
  assert.ok(h.surfaces.every(item => item.inert));
  assert.deepEqual(h.counts(), { unlocked: 1, locked: 1 });
  assert.equal(h.gate.generation(), 2);
});

test("preload bulunmayan web önizlemesi ürün ekranlarına giriş oluşturamaz", async t => {
  const h = fixture(t, deferred(), false); await settle();
  assert.equal(h.gate.allowed(), false);
  assert.equal(h.nodes.get("giris-baslat").disabled, true);
  assert.equal(h.classes.has("session-locked"), true);
});

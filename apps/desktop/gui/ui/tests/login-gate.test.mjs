import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { createLoginGate } from "../src/login-gate.js";

function deferred() {
  let resolve; let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function fixture(t, pending, native = true) {
  const previous = { window: globalThis.window, document: globalThis.document };
  const nodes = new Map(); const classes = new Set(["session-locked"]);
  const node = () => ({ hidden: false, inert: false, attributes: {}, listeners: {}, setAttribute(k, v) { this.attributes[k] = v; }, addEventListener(k, fn) { this.listeners[k] = fn; }, focus() {} });
  const surfaces = [node(), node(), node(), node()];
  let onAccountChange; let unlocked = 0; let locked = 0;
  globalThis.document = { body: { classList: { toggle: (key, value) => value ? classes.add(key) : classes.delete(key) } }, querySelectorAll: selector => selector === "dialog[open]" ? [] : surfaces };
  globalThis.window = { addEventListener() {}, rasathane: native ? { accountStatus: () => pending.promise, onAccountChange: fn => { onAccountChange = fn; return () => {}; } } : undefined };
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

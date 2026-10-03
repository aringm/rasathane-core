"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { createAuthGate } = require("./auth-gate.cjs");

function accountFixture() {
  let generation = 0; let signedIn = false; const listeners = new Set();
  return {
    subscribe: cb => { listeners.add(cb); return () => listeners.delete(cb); },
    requireSession: async () => { if (!signedIn) throw new Error("Muhakeme hesabına giriş gerekli."); return generation; },
    isCurrent: value => signedIn && value === generation,
    set: value => { signedIn = value; generation++; for (const listener of listeners) listener({ state: value ? "signed_in" : "signed_out" }); },
    checkSession: async () => ({ state: signedIn ? "signed_in" : "signed_out" }),
  };
}

test("giriş olmadan hiçbir ürün IPC işlemi başlayamaz; hesap durumu okunur", async () => {
  const account = accountFixture(); const handlers = new Map(); let sideEffects = 0;
  const webContents = { mainFrame: { url: "rasathane://app/index.html" } };
  const electron = { ipcMain: { handle: (name, fn) => handlers.set(name, fn) }, protocol: { registerSchemesAsPrivileged() {} }, dialog: new Proxy({}, { get: () => () => { sideEffects++; } }) };
  const source = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8").split("function bootIz(metin)")[0];
  vm.runInNewContext(source + "\naccount = fixture; authGate = createAuthGate(account); anaPencere = windowFixture; installBridge();", {
    require: name => name === "electron" ? electron : require(name), process, AbortSignal, AbortController, Buffer, setTimeout, clearTimeout,
    fixture: account, windowFixture: { webContents }, fetch: () => { sideEffects++; throw new Error("unauthorized fetch"); },
  });
  const event = { sender: webContents, senderFrame: webContents.mainFrame };
  for (const channel of ["request", "select-workspace", "export-data", "setup-status", "install-models", "open-source"]) {
    await assert.rejects(handlers.get(`rasathane:${channel}`)(event, "/api/rasathane/state"), /giriş gerekli/);
  }
  assert.equal(sideEffects, 0);
  assert.equal((await handlers.get("rasathane:account-status")(event)).state, "signed_out");
});

test("çıkış devam eden isteği iptal eder ve yeni giriş eski yanıtı alamaz", async () => {
  const account = accountFixture(); const gate = createAuthGate(account); account.set(true);
  let release; let ready; const started = new Promise(resolve => { ready = resolve; });
  const result = gate.run(async ({ signal }) => {
    ready(signal); await new Promise(resolve => { release = resolve; }); return { private: "old-session" };
  });
  const rejected = assert.rejects(result, /giriş gerekli/);
  const signal = await started; account.set(false); assert.equal(signal.aborted, true);
  account.set(true); release(); await rejected;
  assert.equal(await gate.run(async () => "new-session"), "new-session"); gate.close();
});

test("korunan işlem ağ veya disk etkisinden hemen önce oturumu tekrar denetleyebilir", async () => {
  const account = accountFixture(); const gate = createAuthGate(account); account.set(true);
  let wrote = false;
  await assert.rejects(gate.run(async ({ assertCurrent }) => { account.set(false); assertCurrent(); wrote = true; }), /giriş gerekli/);
  assert.equal(wrote, false); gate.close();
});

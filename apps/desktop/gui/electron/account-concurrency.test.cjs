"use strict";
const test = require("node:test"); const assert = require("node:assert/strict");
const fs = require("node:fs"); const os = require("node:os"); const path = require("node:path");
const { createAccount } = require("./account.cjs");
const safeStorage = { isEncryptionAvailable: () => true, encryptString: value => Buffer.from(value), decryptString: value => value.toString() };
function record(deviceId, expired = false) {
  return { schema_version: "1.1", device_id: deviceId, durum: "aktif", session_id: "dses_" + "a".repeat(16), access_token: "at_" + "b".repeat(43), refresh_token: "rt_" + "c".repeat(43), scope: ["desktop", "urun:rasathane"], access_sure_sonu: new Date(Date.now() + (expired ? -1000 : 600000)).toISOString(), refresh_sure_sonu: new Date(Date.now() + 3600000).toISOString() };
}
function harness(transport) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-auth-race-")); let opened;
  const account = createAccount({ userData, safeStorage, transport, openExternal: async value => { opened = new URL(value); } });
  return { account, userData, callback: () => { const url = new URL(opened.searchParams.get("redirect_uri")); url.searchParams.set("state", opened.searchParams.get("state")); url.searchParams.set("code", "dc_" + "d".repeat(43)); return url; }, close: () => { account.close(); fs.rmSync(userData, { recursive: true }); } };
}
test("paralel hesap istekleri single-use refresh token'ı bir kez kullanır", async () => {
  let refreshes = 0; let deviceId;
  const h = harness(async (url, request) => {
    const body = request.body && JSON.parse(request.body);
    if (url.endsWith("/exchange")) { deviceId = body.device_id; return Response.json(record(deviceId, true)); }
    if (url.endsWith("/refresh")) { refreshes++; await new Promise(resolve => setTimeout(resolve, 20)); return Response.json(record(deviceId)); }
    return Response.json({ urunler: [] });
  });
  try { await h.account.start(); await fetch(h.callback()); await Promise.all([h.account.entitlement(), h.account.entitlement()]); assert.equal(refreshes, 1); }
  finally { h.close(); }
});
test("çıkış sırasında süren callback hesabı tekrar açamaz", async () => {
  let release; let notify;
  const received = new Promise(resolve => { notify = resolve; });
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness(async (url, request) => { assert.ok(url.endsWith("/exchange")); notify(); await waiting; return Response.json(record(JSON.parse(request.body).device_id)); });
  try {
    await h.account.start(); const callback = fetch(h.callback()); await received; await h.account.signOut(); release();
    assert.equal((await callback).status, 502); assert.equal(h.account.status().state, "signed_out"); assert.equal(fs.existsSync(path.join(h.userData, "account.enc")), false);
  } finally { release(); h.close(); }
});
test("sunucu oturumu reddedince token deposu temizlenir", async () => {
  const h = harness(async (url, request) => url.endsWith("/exchange") ? Response.json(record(JSON.parse(request.body).device_id)) : Response.json({ code: "OTURUM_IPTAL" }, { status: 401 }));
  try { await h.account.start(); await fetch(h.callback()); await assert.rejects(h.account.entitlement()); assert.equal(h.account.status().state, "signed_out"); assert.equal(fs.existsSync(path.join(h.userData, "account.enc")), false); }
  finally { h.close(); }
});

test("eski lisans isteğinin geç 401 yanıtı yeni girişi silemez", async () => {
  let release; let notify;
  const received = new Promise(resolve => { notify = resolve; });
  const waiting = new Promise(resolve => { release = resolve; });
  const h = harness(async (url, request) => {
    if (url.endsWith("/exchange")) return Response.json(record(JSON.parse(request.body).device_id));
    if (url.endsWith("/revoke")) return new Response(null, { status: 204 });
    notify(); await waiting; return Response.json({ code: "OTURUM_IPTAL" }, { status: 401 });
  });
  try {
    await h.account.start(); await fetch(h.callback());
    const oldRequest = assert.rejects(h.account.entitlement()); await received;
    await h.account.signOut(); await h.account.start(); await fetch(h.callback());
    release(); await oldRequest;
    assert.equal(h.account.status().state, "signed_in");
    assert.equal(fs.existsSync(path.join(h.userData, "account.enc")), true);
  } finally { release(); h.close(); }
});

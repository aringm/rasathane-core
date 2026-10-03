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


test("diskteki süresi dolmuş access token giriş durumu oluşturmaz; refresh başarısızsa kilit korunur", async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-expired-"));
  const deviceId = "dev_" + "a".repeat(32);
  fs.writeFileSync(path.join(userData, "device.json"), JSON.stringify({ deviceId }));
  fs.writeFileSync(path.join(userData, "account.enc"), JSON.stringify(record(deviceId, true)));
  const account = createAccount({ userData, safeStorage, openExternal: async () => {}, transport: async () => { throw new Error("offline"); } });
  try {
    assert.equal(account.status().state, "expired");
    assert.equal((await account.checkSession()).state, "expired");
    await assert.rejects(account.requireSession());
  } finally { account.close(); fs.rmSync(userData, { recursive: true }); }
});

test("geçersiz refresh süresi olan disk oturumu hesap ekranını açmaz", async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-refresh-expired-"));
  const deviceId = "dev_" + "a".repeat(32); const value = record(deviceId);
  value.refresh_sure_sonu = new Date(Date.now() - 1000).toISOString();
  fs.writeFileSync(path.join(userData, "device.json"), JSON.stringify({ deviceId }));
  fs.writeFileSync(path.join(userData, "account.enc"), JSON.stringify(value));
  const account = createAccount({ userData, safeStorage, openExternal: async () => {} });
  try { assert.equal(account.status().state, "signed_out"); await assert.rejects(account.requireSession(), /giriş gerekli/); }
  finally { account.close(); fs.rmSync(userData, { recursive: true }); }
});

test("hesap olayı yalnız durum ve scope taşır; canlı token süresi dolunca kilitlenir", async () => {
  const h = harness(async (url, request) => {
    const value = record(JSON.parse(request.body).device_id); value.access_sure_sonu = new Date(Date.now() + 60).toISOString(); return Response.json(value);
  });
  const states = []; const unsub = h.account.subscribe(state => states.push(state));
  try {
    await h.account.start(); await fetch(h.callback());
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.equal(h.account.status().state, "expired");
    assert.ok(states.some(value => value.state === "expired"));
    for (const value of states) assert.deepEqual(Object.keys(value).sort(), ["error", "scope", "state"]);
  } finally { unsub(); h.close(); }
});

test("giriş beklerken reddedilen ürün isteği PKCE dönüşünü geçersiz kılmaz", async () => {
  const h = harness(async (_url, request) => Response.json(record(JSON.parse(request.body).device_id)));
  try {
    await h.account.start();
    await assert.rejects(h.account.requireSession(), /giriş gerekli/);
    assert.equal(h.account.status().state, "waiting");
    assert.equal((await fetch(h.callback())).status, 200);
    assert.equal(h.account.status().state, "signed_in");
  } finally { h.close(); }
});

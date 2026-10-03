"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { createAccount } = require("./account.cjs");
const { createAuthGate } = require("./auth-gate.cjs");
const safeStorage = { isEncryptionAvailable: () => true, encryptString: text => Buffer.from(text).map(byte => byte ^ 0xaa), decryptString: value => Buffer.from(value).map(byte => byte ^ 0xaa).toString() };
const challenge = (wait = 60) => ({ challenge_id: "eotp_" + "a".repeat(43), expires_at: new Date(Date.now() + 600000).toISOString(), resend_after_seconds: wait });
const session = device => ({ schema_version: "1.1", device_id: device, durum: "aktif", session_id: "dses_" + "b".repeat(16), access_token: "at_" + "c".repeat(43), refresh_token: "rt_" + "d".repeat(43), scope: ["desktop", "urun:rasathane"], access_sure_sonu: new Date(Date.now() + 600000).toISOString(), refresh_sure_sonu: new Date(Date.now() + 3600000).toISOString() });
function harness(transport) {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-email-")); const events = [];
  const account = createAccount({ userData, safeStorage, openExternal: () => { throw new Error("OTP must not open browser"); }, transport });
  account.subscribe(value => events.push(value));
  return { userData, account, events, close() { account.close(); fs.rmSync(userData, { recursive: true }); } };
}

test("e-posta kodu aynı cihaz + PKCE ile doğrulanır; gate açılır, şifreli oturum yeniden yüklenir", async () => {
  let requested;
  const h = harness(async (url, request) => {
    assert.equal(new URL(url).origin, "https://www.muhakeme.ai");
    const input = JSON.parse(request.body);
    if (url.endsWith("/email/request")) { assert.equal(input.code_challenge_method, "S256"); requested = input; return Response.json(challenge()); }
    assert.ok(url.endsWith("/email/verify"));
    assert.equal(input.email, "ornek@example.com"); assert.equal(input.device_id, requested.device_id);
    assert.equal(input.client_id, "rasathane-desktop"); assert.equal(input.challenge_id, challenge().challenge_id);
    assert.equal(crypto.createHash("sha256").update(input.code_verifier).digest("base64url"), requested.code_challenge);
    assert.equal(input.code, "123456"); return Response.json(session(input.device_id));
  });
  const gate = createAuthGate(h.account);
  try {
    await assert.rejects(gate.run(async () => "blocked"));
    const sent = await h.account.sendLoginCode("  Ornek@example.com  ");
    assert.equal(sent.state, "code_sent"); assert.equal(sent.login.email, "ornek@example.com");
    await assert.rejects(gate.run(async () => "still blocked"));
    assert.equal((await h.account.verifyLoginCode("123456")).state, "signed_in");
    assert.equal(await gate.run(async () => "allowed"), "allowed");
    assert.equal(fs.readFileSync(path.join(h.userData, "account.enc")).includes(Buffer.from("access_token")), false);
    for (const state of h.events) assert.doesNotMatch(JSON.stringify(state), /at_|rt_|eotp_|verifier|challenge|123456/);
    const restarted = createAccount({ userData: h.userData, safeStorage, openExternal: () => {} });
    assert.equal(restarted.status().state, "signed_in"); restarted.close();
  } finally { gate.close(); h.close(); }
});

test("yanlış veya biçimi bozuk kod yeniden denenebilir; raw sunucu hatası renderer'a sızmaz", async () => {
  let verifications = 0;
  const h = harness(async (url, request) => {
    if (url.endsWith("/request")) return Response.json(challenge());
    if (++verifications === 1) return Response.json({ code: "OTP_GECERSIZ", message: "secret server data" }, { status: 400 });
    return Response.json(session(JSON.parse(request.body).device_id));
  });
  try {
    await h.account.sendLoginCode("ornek@example.com");
    assert.equal((await h.account.verifyLoginCode({ code: "123456" })).errorCode, "wrong_code"); assert.equal(verifications, 0);
    const wrong = await h.account.verifyLoginCode("000000");
    assert.equal(wrong.state, "code_sent"); assert.equal(wrong.errorCode, "wrong_code"); assert.doesNotMatch(wrong.error, /secret/);
    assert.equal((await h.account.verifyLoginCode("123456")).state, "signed_in");
  } finally { h.close(); }
});

test("resend sayaç tamamlanmadan ağ çağrısı yapmaz; yeni kod farklı PKCE ile eski challenge'ı değiştirir", async () => {
  const requests = [];
  const h = harness(async (_url, request) => { requests.push(JSON.parse(request.body)); return Response.json(challenge(requests.length === 1 ? 0 : 60)); });
  try {
    await h.account.sendLoginCode("ornek@example.com"); await h.account.sendLoginCode("ornek@example.com");
    assert.notEqual(requests[0].code_challenge, requests[1].code_challenge);
    assert.equal((await h.account.sendLoginCode("ornek@example.com")).errorCode, "rate_limited"); assert.equal(requests.length, 2);
  } finally { h.close(); }
});

for (const action of ["cancel", "signOut", "close"]) test(`${action} sonrası geç doğrulama oturum açamaz`, async () => {
  let release; let notify;
  const received = new Promise(resolve => { notify = resolve; }); const waiting = new Promise(resolve => { release = resolve; });
  const h = harness(async (url, request) => {
    if (url.endsWith("/request")) return Response.json(challenge());
    notify(); await waiting; return Response.json(session(JSON.parse(request.body).device_id));
  });
  try {
    await h.account.sendLoginCode("ornek@example.com"); const verifying = h.account.verifyLoginCode("123456"); await received;
    if (action === "cancel") h.account.cancelLogin(); else if (action === "signOut") await h.account.signOut(); else h.account.close();
    release(); await verifying; assert.notEqual(h.account.status().state, "signed_in"); assert.equal(fs.existsSync(path.join(h.userData, "account.enc")), false);
  } finally { release(); h.close(); }
});

test("iptal edilmiş gönderim yanıtı yeni e-posta akışını değiştiremez; pending challenge diske yazılmaz", async () => {
  let release; let notify; let requests = 0;
  const received = new Promise(resolve => { notify = resolve; }); const waiting = new Promise(resolve => { release = resolve; });
  const h = harness(async () => { if (++requests === 1) { notify(); await waiting; } return Response.json(challenge()); });
  try {
    const sending = h.account.sendLoginCode("eski@example.com"); await received; h.account.cancelLogin();
    await h.account.sendLoginCode("yeni@example.com"); release(); await sending;
    assert.equal(h.account.status().login.email, "yeni@example.com"); assert.deepEqual(fs.readdirSync(h.userData), ["device.json"]);
  } finally { release(); h.close(); }
});

test("süresi dolan veya deneme sınırına ulaşan kod tekrar doğrulanmaz; rate limit güvenli sayaç döndürür", async () => {
  let code = "OTP_SURESI_DOLDU"; let verifications = 0;
  const h = harness(async url => {
    if (url.endsWith("/request")) return Response.json(challenge(0));
    verifications++; return Response.json({ code }, { status: code === "HIZ_SINIRI" ? 429 : 400, headers: { "Retry-After": "120" } });
  });
  try {
    for (const value of ["OTP_SURESI_DOLDU", "OTP_DENEME_SINIRI"]) {
      code = value; await h.account.sendLoginCode("ornek@example.com"); assert.equal((await h.account.verifyLoginCode("123456")).errorCode, "expired_code");
      const calls = verifications; await h.account.verifyLoginCode("123456"); assert.equal(verifications, calls);
    }
    code = "HIZ_SINIRI"; await h.account.sendLoginCode("ornek@example.com"); const result = await h.account.verifyLoginCode("123456");
    assert.equal(result.errorCode, "rate_limited"); assert.ok(Date.parse(result.login.resendAt) > Date.now() + 110000);
    const calls = verifications; await h.account.verifyLoginCode("123456"); assert.equal(verifications, calls);
  } finally { h.close(); }
});

test("preload → trusted IPC → OTP sözleşmesi token taşımaz; giriş belgeleri dar allowlist kullanır", async () => {
  const vm = require("node:vm"); const handlers = new Map(); const opened = []; let exposed;
  const frame = { url: "rasathane://app/index.html" }; const webContents = { mainFrame: frame };
  const event = { sender: webContents, senderFrame: frame }; const callbacks = new Map();
  const electron = {
    ipcMain: { handle: (name, callback) => handlers.set(name, callback) }, protocol: { registerSchemesAsPrivileged() {} },
    shell: { openExternal: async url => opened.push(url) }, contextBridge: { exposeInMainWorld: (_name, api) => { exposed = api; } },
    ipcRenderer: { invoke: (channel, ...args) => handlers.get(channel)(event, ...args), on: (channel, callback) => callbacks.set(channel, callback), removeListener: channel => callbacks.delete(channel) },
  };
  const h = harness(async (url, request) => url.endsWith("/request") ? Response.json(challenge()) : Response.json(session(JSON.parse(request.body).device_id)));
  const requireFixture = name => name === "electron" ? electron : require(name);
  const source = fs.readFileSync(path.join(__dirname, "main.cjs"), "utf8").split("function bootIz(metin)")[0];
  const context = { require: requireFixture, process, AbortSignal, AbortController, Buffer, setTimeout, clearTimeout, fixture: h.account, windowFixture: { webContents } };
  vm.runInNewContext(source + "\naccount = fixture; authGate = createAuthGate(account); anaPencere = windowFixture; installBridge();", context);
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "preload.cjs"), "utf8"), { require: requireFixture });
  try {
    for (const channel of ["send-login-code", "verify-login-code", "cancel-login", "open-login-document"]) {
      await assert.rejects(async () => handlers.get(`rasathane:${channel}`)({ sender: webContents, senderFrame: { url: frame.url } }, "anything"), /İstek kaynağı/);
    }
    await exposed.openLoginDocument("terms"); await exposed.openLoginDocument("privacy");
    await assert.rejects(exposed.openLoginDocument("https://evil.test"), /Belge seçimi/);
    assert.deepEqual(opened, ["https://www.muhakeme.ai/kosullar", "https://www.muhakeme.ai/kvkk"]);
    const sent = await exposed.sendLoginCode("ornek@example.com"); assert.equal(sent.state, "code_sent");
    let observed; const unsubscribe = exposed.onAccountChange(value => { observed = value; });
    callbacks.get("rasathane:account-change")({}, { ...sent, access_token: "not-for-renderer", refresh_token: "not-for-renderer" });
    assert.equal(observed.login.email, "ornek@example.com"); assert.equal(observed.access_token, undefined); assert.equal(observed.refresh_token, undefined); unsubscribe();
    assert.equal((await exposed.verifyLoginCode("123456")).state, "signed_in");
    await exposed.signOut(); assert.equal((await exposed.cancelLogin()).state, "signed_out");
  } finally { h.close(); }
});

test("geçersiz girdi, uyumsuz scope ve token taşıyan sunucu yanıtı güvenli biçimde reddedilir", async () => {
  let calls = 0;
  const h = harness(async (url, request) => {
    calls++;
    if (url.endsWith("/request")) return Response.json(challenge());
    return Response.json({ ...session(JSON.parse(request.body).device_id), scope: ["desktop", "urun:muhakeme"] });
  });
  try {
    for (const value of [null, {}, "bad", "a\nb@example.com", "a".repeat(255)]) assert.equal((await h.account.sendLoginCode(value)).errorCode, "invalid_email");
    assert.equal(calls, 0); await h.account.sendLoginCode("ornek@example.com");
    assert.equal((await h.account.verifyLoginCode("123456")).errorCode, "unavailable");
    assert.equal(fs.existsSync(path.join(h.userData, "account.enc")), false);
  } finally { h.close(); }
});

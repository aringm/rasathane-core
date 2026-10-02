"use strict";
const test = require("node:test"); const assert = require("node:assert/strict");
const fs = require("node:fs"); const os = require("node:os"); const path = require("node:path");
const { createAccount } = require("./account.cjs");

test("gerçek loopback PKCE dönüşü; yanlış state reddi ve scope kontrollü encrypted storage", async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-account-")); let opened; let exchanges = 0;
  const fakeStorage = { isEncryptionAvailable: () => true, encryptString: text => Buffer.from(text).map(byte => byte ^ 0xaa), decryptString: buffer => Buffer.from(buffer).map(byte => byte ^ 0xaa).toString() };
  const transport = async (url, request) => {
    assert.equal(new URL(url).origin, "https://www.muhakeme.ai"); const input = request.body ? JSON.parse(request.body) : null;
    if (url.endsWith("/exchange")) {
      exchanges++; assert.equal(input.client_id, "rasathane-desktop"); assert.equal(input.code_verifier.length, 43);
      return Response.json({ schema_version: "1.1", device_id: input.device_id, durum: "aktif", session_id: "dses_"+"a".repeat(16), access_token: "at_"+"b".repeat(43), refresh_token: "rt_"+"c".repeat(43), scope: ["desktop","urun:rasathane"], access_sure_sonu: new Date(Date.now()+600000).toISOString(), refresh_sure_sonu: new Date(Date.now()+3600000).toISOString() });
    }
    assert.match(request.headers.Authorization, /^Bearer at_/);
    if (url.endsWith("/revoke")) return new Response(null, { status: 204 });
    return Response.json({ urunler: [{ urun: "rasathane", durum: "yok" }] });
  };
  const account = createAccount({ userData, safeStorage: fakeStorage, openExternal: async value => { opened = new URL(value); }, transport });
  try {
    await account.start(); assert.equal(account.status().state, "waiting"); assert.equal(opened.searchParams.get("response_type"), "code"); const callback = new URL(opened.searchParams.get("redirect_uri")); callback.searchParams.set("code", "dc_"+"x".repeat(43)); callback.searchParams.set("state", "invalid");
    assert.equal((await fetch(callback)).status, 400); assert.equal(exchanges, 0);
    callback.searchParams.set("state", opened.searchParams.get("state")); assert.equal((await fetch(callback)).status, 200);
    assert.equal(account.status().state, "signed_in"); assert.equal(exchanges, 1); assert.equal(fs.readFileSync(path.join(userData,"account.enc")).includes(Buffer.from("refresh_token")), false);
    assert.equal((await account.entitlement()).urunler[0].urun, "rasathane");
    assert.deepEqual(await account.signOut(), { signedOut: true, remoteRevoked: true });
    assert.equal(fs.existsSync(path.join(userData, "account.enc")), false);
  } finally { account.close(); fs.rmSync(userData, { recursive: true }); }
});

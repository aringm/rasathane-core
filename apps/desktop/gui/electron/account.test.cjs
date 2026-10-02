"use strict";
const test = require("node:test"); const assert = require("node:assert/strict");
const crypto = require("node:crypto"); const { pkcePair, validSession } = require("./account.cjs");
test("PKCE ayrı state ve S256 challenge", () => { const pair = pkcePair(); assert.equal(pair.verifier.length, 43); assert.equal(pair.challenge, crypto.createHash("sha256").update(pair.verifier).digest("base64url")); assert.notEqual(pair.state, pair.verifier); });
test("başka ürün ve cihaz token'ı alınmaz", () => {
 const record = { schema_version:"1.1",device_id:"dev_"+"a".repeat(32),durum:"aktif",session_id:"dses_"+"b".repeat(16),access_token:"at_"+"x".repeat(43),refresh_token:"rt_"+"y".repeat(43),scope:["desktop","urun:rasathane"],access_sure_sonu:new Date().toISOString(),refresh_sure_sonu:new Date().toISOString() };
 assert.equal(validSession(record, record.device_id), true); assert.equal(validSession(record,"other"), false); assert.equal(validSession({...record,scope:["desktop"]}, record.device_id), false); assert.equal(validSession({...record,scope:["desktop","urun:rasathane","admin"]}, record.device_id), false);
});

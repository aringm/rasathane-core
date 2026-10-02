"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { validateRequest, trustedSender } = require("./ipc-policy.cjs");

test("dar API sözleşmesi ve tek iş iptali", () => {
  assert.deepEqual(validateRequest("/api/rasathane/jobs/job_123/cancel", { method: "POST", body: {} }), { route: "/api/rasathane/jobs/job_123/cancel", method: "POST", body: "{}" });
  assert.equal(validateRequest("/gui/dosya?ad=06.pdf&klasor=test").method, "GET");
  assert.equal(validateRequest("/api/rasathane/jobs/abc123").method, "GET");
  assert.throws(() => validateRequest("/api/rasathane/jobs/abc123", { method: "POST", body: {} }));
});
test("URL, traversal, method ve header injection engellenir", () => {
  for (const route of ["https://evil.test", "//evil.test", "/api/../gui/health", "/api/rasathane/../../health", "/gui\\health", "/gui/health#x", "/admin", "/gui/%2e%2e/health"]) assert.throws(() => validateRequest(route));
  assert.throws(() => validateRequest("/gui/ayarlar", { method: "POST", body: { motor_kok: "C:/untrusted" } }));
  assert.throws(() => validateRequest("/api/product/service-session", { method: "POST", body: { access_token: "at_" + "a".repeat(43) } }));
  assert.throws(() => validateRequest("/gui/health", { headers: { Origin: "evil" } }));
  assert.throws(() => validateRequest("/gui/health", { body: {} }));
  assert.throws(() => validateRequest("/api/rasathane/notes", { method: "POST", body: { body: "a".repeat(40000) } }));
});
test("uzak veya credential içeren model host kabul edilmez", () => {
  for (const host of ["http://evil.test", "http://127.0.0.1.evil.test", "http://user:pass@localhost", "https://127.0.0.1"]) assert.throws(() => validateRequest("/gui/ollama_test", { method: "POST", body: { host } }));
  assert.equal(validateRequest("/gui/ollama_test", { method: "POST", body: { host: "http://127.0.0.1:11434" } }).method, "POST");
});
test("yalnız ana renderer ve exact custom origin", () => {
  const frame = { url: "rasathane://app/index.html" }; const contents = { mainFrame: frame }; const window = { webContents: contents };
  assert.equal(trustedSender({ sender: contents, senderFrame: frame }, window), true);
  assert.equal(trustedSender({ sender: contents, senderFrame: { url: "rasathane://app/index.html" } }, window), false);
  frame.url = "rasathane://app.evil/index.html";
  assert.equal(trustedSender({ sender: contents, senderFrame: frame }, window), false);
});

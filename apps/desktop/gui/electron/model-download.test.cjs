"use strict";
const test = require("node:test"); const assert = require("node:assert/strict");
const fs = require("node:fs"); const os = require("node:os"); const path = require("node:path"); const crypto = require("node:crypto");
const { createModelSetup } = require("./model-setup.cjs");
const body = Buffer.from("küçük model fixture");
const specification = { name: "model.gguf", bytes: body.length, license: "MIT", sha256: crypto.createHash("sha256").update(body).digest("hex"), url: "https://huggingface.co/test/model/resolve/fixed/model.gguf" };
async function settled(manager) {
  for (let i = 0; i < 200; i++) { const result = await manager.inspect(); if (["completed", "failed"].includes(result.state)) return result; await new Promise(resolve => setTimeout(resolve, 5)); }
  throw new Error("Test indirmesi tamamlanmadı.");
}
for (const [name, transport, success] of [
  ["diskteki model byte ve SHA256 doğrulanır", async () => new Response(body), true],
  ["yanlış SHA256 hedef dosyaya dönüştürülmez", async () => new Response(Buffer.alloc(body.length)), false],
  ["fazla byte hedef dosyaya dönüştürülmez", async () => new Response(Buffer.concat([body, body])), false],
  ["model farklı HTTPS host'a yönlendirilemez", async () => new Response(null, { status: 302, headers: { Location: "https://evil.example/model.gguf" } }), false],
]) test(name, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-download-"));
  try {
    const manager = createModelSetup(root, { models: [specification], transport });
    assert.equal((await manager.inspect()).ready, false); manager.start(); const result = await settled(manager);
    assert.equal(result.state, success ? "completed" : "failed"); assert.equal(result.ready, success); assert.equal(result.requiredBytes, body.length);
    const target = path.join(root, "modeller", specification.name); assert.equal(fs.existsSync(target), success);
    if (success) assert.deepEqual(fs.readFileSync(target), body);
  } finally { fs.rmSync(root, { recursive: true }); }
});

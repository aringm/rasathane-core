"use strict";
const test = require("node:test"); const assert = require("node:assert/strict");
const fs = require("node:fs"); const os = require("node:os"); const path = require("node:path");
const { safeDownloadURL, createModelSetup, sha256 } = require("./model-setup.cjs");
test("model redirect exact HTTPS sağlayıcı alanları", () => {
  assert.equal(safeDownloadURL("https://cas-bridge.xethub.hf.co/file"), "https://cas-bridge.xethub.hf.co/file");
  for (const url of ["http://huggingface.co/a", "https://huggingface.co.evil/a", "https://user:pass@hf.co/a", "https://127.0.0.1/a"]) assert.throws(() => safeDownloadURL(url));
});
test("eksik ve değiştirilmiş model hazır sayılmaz", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-model-test-"));
  try { const status = await createModelSetup(root).inspect(); assert.equal(status.ready, false); assert.equal(status.models.length, 2);
    const file = path.join(root, "data"); fs.writeFileSync(file, "abc"); assert.equal(await sha256(file), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  } finally { fs.rmSync(root, { recursive: true }); }
});

test("paralel model kontrolleri aynı checksum işini paylaşır", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-model-concurrent-"));
  try {
    const setup = createModelSetup(root); const first = setup.inspect(); const second = setup.inspect();
    assert.equal(first, second); assert.equal((await first).ready, false);
    assert.notEqual(setup.inspect(), first);
  } finally { fs.rmSync(root, { recursive: true }); }
});

test("çıkış model indirmesini iptal eder ve tamamlanmış model oluşturmaz", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "rasathane-model-cancel-"));
  let started; const ready = new Promise(resolve => { started = resolve; });
  const setup = createModelSetup(root, {
    models: [{ name: "fixture.gguf", bytes: 3, sha256: "0".repeat(64), url: "https://hf.co/fixture", license: "test" }],
    transport: async (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(new Error("İndirme iptal edildi.")), { once: true }); started(signal);
    }),
  });
  try {
    setup.start(); const signal = await ready; setup.cancel(); assert.equal(signal.aborted, true);
    for (let i = 0; i < 20 && (await setup.inspect()).state !== "failed"; i++) await new Promise(resolve => setTimeout(resolve, 5));
    assert.equal((await setup.inspect()).state, "failed");
    assert.equal(fs.existsSync(path.join(root, "modeller", "fixture.gguf")), false);
  } finally { setup.cancel(); fs.rmSync(root, { recursive: true }); }
});

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

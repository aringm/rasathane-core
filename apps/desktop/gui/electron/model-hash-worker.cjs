"use strict";
const fs = require("node:fs");
const crypto = require("node:crypto");
const { parentPort, workerData } = require("node:worker_threads");

// Sabit main script'i; renderer dosya yolu veya worker kodu seçemez. Sabit
// buffer ile büyük GGUF doğrulaması main event loop'unu ve RAM'i doldurmaz.
let descriptor;
try {
  descriptor = fs.openSync(workerData.file, "r");
  const hash = crypto.createHash("sha256"); const buffer = Buffer.allocUnsafe(1024 * 1024);
  let count;
  while ((count = fs.readSync(descriptor, buffer, 0, buffer.length, null)) > 0) hash.update(buffer.subarray(0, count));
  parentPort.postMessage({ sha256: hash.digest("hex") });
} catch (problem) {
  parentPort.postMessage({ error: String(problem.message) });
} finally { if (descriptor !== undefined) fs.closeSync(descriptor); }

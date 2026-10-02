"use strict";
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { Worker } = require("node:worker_threads");
const catalog = require("./model-catalog.json");

async function sha256(file) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(path.join(__dirname, "model-hash-worker.cjs"), { workerData: { file } });
    const timer = setTimeout(() => { void worker.terminate(); reject(new Error("Model checksum kontrolü zaman aşımına uğradı.")); }, 180000);
    worker.once("message", result => {
      clearTimeout(timer);
      if (/^[a-f0-9]{64}$/.test(result?.sha256 || "")) resolve(result.sha256);
      else reject(new Error(result?.error || "Model checksum yanıtı geçersiz."));
    });
    worker.once("error", error => { clearTimeout(timer); reject(error); });
    worker.once("exit", code => { clearTimeout(timer); if (code !== 0) reject(new Error("Model checksum worker'ı kapandı.")); });
  });
}
function safeDownloadURL(value) {
  const url = new URL(value);
  if (url.protocol !== "https:" || url.username || url.password || !["huggingface.co", "hf.co", "xethub.hf.co", "cdn-lfs.huggingface.co", "cdn-lfs.hf.co"].some(host => url.hostname === host || url.hostname.endsWith(`.${host}`))) throw new Error("Model indirme hedefi izinli değil.");
  return url.href;
}
function createModelSetup(root, { models: specifications = catalog, transport = fetch } = {}) {
  let status = { state: "idle", received: 0, total: 0, model: null, error: null };
  let pending = null;
  let inspecting = null;
  const verified = new Map();
  async function inspectFiles() {
    const models = [];
    for (const item of specifications) {
      const file = path.join(root, "modeller", item.name);
      const stat = fs.existsSync(file) ? fs.statSync(file) : null;
      const stamp = stat ? `${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}` : "missing";
      const cached = verified.get(file);
      const ready = stat?.size === item.bytes && (cached?.stamp === stamp ? cached.ready : await sha256(file) === item.sha256);
      verified.set(file, { stamp, ready });
      models.push({ name: item.name, bytes: item.bytes, license: item.license,
        ready: Boolean(ready) });
    }
    return { ...status, ready: models.every(item => item.ready), models, requiredBytes: specifications.reduce((sum, item) => sum + item.bytes, 0) };
  }
  function inspect() {
    // İlk kurulum, Ayarlar ve QA aynı anda checksum isteyebilir. Aynı dosya
    // üç kez okunmaz; bütün çağrılar tek doğrulama sonucunu paylaşır.
    if (!inspecting) {
      const task = inspectFiles(); inspecting = task;
      task.finally(() => { if (inspecting === task) inspecting = null; }).catch(() => {});
    }
    return inspecting;
  }
  async function install() {
    fs.mkdirSync(path.join(root, "modeller"), { recursive: true });
    const disk = fs.statfsSync(root);
    if (disk.bavail * disk.bsize < specifications.reduce((sum, item) => sum + item.bytes, 0) + 512 * 1024 * 1024) throw new Error("Model kurulumu için en az 3,5 GB boş disk alanı gerekli.");
    for (const item of specifications) {
      const target = path.join(root, "modeller", item.name);
      if (fs.existsSync(target) && fs.statSync(target).size === item.bytes && await sha256(target) === item.sha256) continue;
      status = { state: "downloading", received: 0, total: item.bytes, model: item.name, error: null };
      let url = safeDownloadURL(item.url); let response;
      for (let count = 0; count < 8; count++) {
        response = await transport(url, { redirect: "manual", signal: AbortSignal.timeout(3600000) });
        if (response.status >= 300 && response.status < 400) {
          const next = response.headers.get("location"); await response.body?.cancel();
          if (!next) throw new Error("Model yönlendirme hedefi eksik.");
          url = safeDownloadURL(new URL(next, url).href); continue;
        }
        break;
      }
      if (!response?.ok || !response.body) throw new Error(`Model indirilemedi (${response?.status || "bağlantı"}).`);
      const partial = `${target}.partial`; const handle = await fs.promises.open(partial, "w");
      const hash = crypto.createHash("sha256");
      try {
        for await (const chunk of response.body) {
          status.received += chunk.length;
          if (status.received > item.bytes) throw new Error("Model boyutu beklenenden büyük.");
          hash.update(chunk); await handle.writeFile(chunk);
        }
      } finally { await handle.close(); }
      if (status.received !== item.bytes || hash.digest("hex") !== item.sha256) throw new Error("Model SHA256 doğrulaması başarısız. Analiz için kullanılmadı.");
      if (fs.statSync(partial).size !== item.bytes || await sha256(partial) !== item.sha256) throw new Error("Diske yazılan model SHA256 doğrulaması başarısız.");
      await fs.promises.rename(partial, target);
    }
    status.state = "completed"; status.error = null;
  }
  return {
    inspect,
    start: () => {
      if (!pending) {
        pending = install().catch(error => { status.state = "failed"; status.error = String(error.message); }).finally(() => { pending = null; });
      }
      return { started: true };
    },
  };
}
module.exports = { createModelSetup, safeDownloadURL, sha256 };

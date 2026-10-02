"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { spawn, spawnSync } = require("node:child_process");
const nodeNet = require("node:net");
const crypto = require("node:crypto");
const { app, BrowserWindow, dialog, ipcMain, net, protocol, session, shell, safeStorage } = require("electron");
const { validateRequest, trustedSender, publicSourceURL } = require("./ipc-policy.cjs");
const { createModelSetup } = require("./model-setup.cjs");
const { createAccount } = require("./account.cjs");

const SCHEME = "rasathane";
const APP_ORIGIN = `${SCHEME}://app`;
const SMOKE_MODE = process.argv.includes("--smoke-test");
const SMOKE_ANALYSIS = SMOKE_MODE && process.argv.includes("--smoke-analysis");
// Motor portu artık sabit değil: 8765'i başka bir uygulama tutuyorsa sidecar bind
// hatasıyla ölüyor ve arayüzde yalnız "Motor başlatılamadı" kalıyordu. Açılışta
// listedeki ilk boş port seçilir, sidecar'a env ile sürülür ve arayüze query ile
// bildirilir. Liste index.html CSP connect-src/frame-src ile birebir aynı olmalı.
const ADAY_PORTLAR = [8765, 8766, 8767, 8768];

protocol.registerSchemesAsPrivileged([
  {
    scheme: SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);
// Global app.enableSandbox(), Electron 43 + Windows'ta standard custom protocol ilk
// navigasyonunda native crash üretiyor. Tek renderer aşağıda sandbox:true ile açıkça
// sandbox'a alınır; yeni pencere/webview/izin yolları ayrıca deny-by-default kapalıdır.

let anaPencere = null;
let sidecarPort = ADAY_PORTLAR[0];
let sidecar = null;
let sidecarLog = null;
let kapaniyor = false;
const sessionToken = crypto.randomBytes(32).toString("hex");
let modelSetup;
let account;

function userSettings() {
  try { return JSON.parse(fs.readFileSync(path.join(app.getPath("userData"), "desktop-settings.json"), "utf8")); }
  catch { return {}; }
}

function installBridge() {
  function check(event) {
    if (!trustedSender(event, anaPencere)) throw new Error("İstek kaynağı izinli değil.");
  }
  ipcMain.handle("rasathane:request", async (event, route, options) => {
    check(event);
    const request = validateRequest(route, options);
    // Hosted kaynak takibi için token yalnız main → loopback belleğine geçer.
    // Renderer allowlist bu dahili endpoint'i içermez; token JSON response'a girmez.
    if (request.method === "POST" && /^\/api\/rasathane\/sources\/[^/]+\/refresh$/.test(request.route)) {
      let accessToken = null;
      if (account.status().state === "signed_in") { try { accessToken = await account.serviceAccessToken(); } catch { /* kamu kaynakları hesap olmadan da yenilenir */ } }
      const configured = await fetch(`http://127.0.0.1:${sidecarPort}/api/product/service-session`, {
        method: "POST", redirect: "error", signal: AbortSignal.timeout(20000),
        headers: { "Content-Type": "application/json", Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken },
        body: JSON.stringify({ access_token: accessToken }),
      });
      if (!configured.ok) throw new Error("Kaynak servisi hesap bağlantısı kurulamadı.");
      await configured.body?.cancel();
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000);
    try {
      const response = await fetch(`http://127.0.0.1:${sidecarPort}${request.route}`, {
        method: request.method, body: request.body, redirect: "error", signal: controller.signal,
        headers: { "Content-Type": "application/json", Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken },
      });
      const cap = 8 * 1024 * 1024;
      if (Number(response.headers.get("content-length")) > cap) { await response.body?.cancel(); throw new Error("Yanıt sınırı aşıldı."); }
      const chunks = []; let size = 0;
      if (response.body) for await (const chunk of response.body) {
        size += chunk.length; if (size > cap) { controller.abort(); throw new Error("Yanıt sınırı aşıldı."); } chunks.push(Buffer.from(chunk));
      }
      const buffer = Buffer.concat(chunks);
      const contentType = response.headers.get("content-type") || "application/octet-stream";
      if (contentType.includes("application/json")) return { ok: response.ok, status: response.status, contentType, data: JSON.parse(buffer.toString("utf8")) };
      return { ok: response.ok, status: response.status, contentType, data: null, base64: buffer.toString("base64") };
    } finally { clearTimeout(timer); }
  });
  ipcMain.handle("rasathane:select-workspace", async event => {
    check(event);
    const result = await dialog.showOpenDialog(anaPencere, { title: "Rasathane çalışma alanı", properties: ["openDirectory", "createDirectory"] });
    if (result.canceled || !result.filePaths[0]) return { cancelled: true };
    const selected = path.resolve(result.filePaths[0]);
    const settingsPath = path.join(app.getPath("userData"), "desktop-settings.json");
    fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
    fs.writeFileSync(`${settingsPath}.tmp`, JSON.stringify({ ...userSettings(), workspace: selected }, null, 2), { encoding: "utf8", mode: 0o600 });
    fs.renameSync(`${settingsPath}.tmp`, settingsPath);
    return { cancelled: false, path: selected, restartRequired: true };
  });
  ipcMain.handle("rasathane:export-data", async (event, workspaceId) => {
    check(event);
    if (workspaceId !== null && (typeof workspaceId !== "string" || !/^[a-f0-9]{32}$/.test(workspaceId))) throw new Error("Çalışma alanı kimliği geçersiz.");
    const choice = await dialog.showSaveDialog(anaPencere, { title: "Rasathane verisini dışa aktar", defaultPath: path.join(app.getPath("documents"), "rasathane-calisma-alani.json"), filters: [{ name: "JSON", extensions: ["json"] }] });
    if (choice.canceled || !choice.filePath) return { cancelled: true };
    const file = path.resolve(choice.filePath); const temporary = `${file}.${crypto.randomBytes(8).toString("hex")}.partial`;
    let handle;
    try {
      const response = await fetch(`http://127.0.0.1:${sidecarPort}/api/rasathane/export${workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ""}`, { redirect: "error", signal: AbortSignal.timeout(120000), headers: { Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken } });
      if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("application/json")) throw new Error("Dışa aktarma yanıtı alınamadı.");
      handle = await fs.promises.open(temporary, "wx", 0o600); let bytes = 0; const hash = crypto.createHash("sha256");
      for await (const chunk of response.body) { bytes += chunk.length; if (bytes > 256 * 1024 * 1024) throw new Error("Dışa aktarma boyutu 256 MB sınırını aştı; çalışma alanını seçerek yeniden deneyin."); hash.update(chunk); await handle.writeFile(chunk); }
      await handle.sync(); await handle.close(); handle = null; await fs.promises.rename(temporary, file);
      return { saved: true, path: file, bytes, sha256: hash.digest("hex") };
    } finally { if (handle) await handle.close(); if (fs.existsSync(temporary)) await fs.promises.unlink(temporary); }
  });
  ipcMain.handle("rasathane:open-account", async event => {
    check(event); return account.start();
  });
  ipcMain.handle("rasathane:account-status", event => { check(event); return account.status(); });
  ipcMain.handle("rasathane:entitlement", async event => { check(event); return account.entitlement(); });
  ipcMain.handle("rasathane:start-trial", async event => { check(event); return account.startTrial(); });
  ipcMain.handle("rasathane:sign-out", async event => {
    check(event); const result = await account.signOut();
    try { const response = await fetch(`http://127.0.0.1:${sidecarPort}/api/product/service-session`, { method: "POST", redirect: "error", signal: AbortSignal.timeout(5000), headers: { "Content-Type": "application/json", Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken }, body: JSON.stringify({ access_token: null }) }); await response.body?.cancel(); } catch { /* sidecar kapalıysa bellek de yoktur */ }
    return result;
  });
  ipcMain.handle("rasathane:setup-status", async event => {
    check(event); bootIz("model kontrolü başladı");
    const result = await modelSetup.inspect(); bootIz(`model kontrolü bitti: ${result.ready}`); return result;
  });
  ipcMain.handle("rasathane:open-source", async (event, url) => { check(event); await shell.openExternal(publicSourceURL(url)); return { opened: true }; });
  ipcMain.handle("rasathane:install-models", async event => { check(event); return modelSetup.start(); });
}

function bootIz(metin) {
  if (process.env.RASATHANE_DEBUG_BOOT === "1") console.error(`[boot] ${metin}`);
}

function uygulamaKoku() {
  return app.getAppPath();
}

function arayuzKoku() {
  return path.resolve(uygulamaKoku(), "ui");
}

function sidecarYolu() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "sidecar", "ytanaliz-sidecar.exe");
  }
  return path.resolve(__dirname, "..", "..", "infra", "dist", "ytanaliz-sidecar.exe");
}

// Gömülü llama.cpp motoru (llama-server.exe + GGUF modelleri). Paketli kurulumda
// resources/motor, geliştirmede infra/vendor/motor. Sidecar bu kökten llama-server
// proseslerini kendisi başlatır; taskkill /T ile sidecar ağacı kapanırken onlar da ölür.
function motorKoku() {
  if (app.isPackaged) {
    return path.join(app.getPath("userData"), "motor");
  }
  return path.resolve(__dirname, "..", "..", "infra", "vendor", "motor");
}

function packagedModels() {
  return app.isPackaged ? path.join(process.resourcesPath, "motor", "modeller") : path.join(motorKoku(), "modeller");
}

function prepareMotor() {
  if (app.isPackaged) {
    const binary = path.join(motorKoku(), "bin");
    fs.mkdirSync(motorKoku(), { recursive: true });
    // Bunlar installer'ın taşıdığı sabit binary'lerdir; model weights userData'dadır.
    fs.cpSync(path.join(process.resourcesPath, "motor", "bin"), binary, { recursive: true, force: true });
  }
  modelSetup = createModelSetup(motorKoku());
}

function guvenliArayuzDosyasi(urlMetni) {
  const url = new URL(urlMetni);
  if (url.host !== "app") return null;
  const hamYol = decodeURIComponent(url.pathname);
  const goreli = hamYol === "/" ? "index.html" : hamYol.replace(/^\/+/, "");
  const kok = arayuzKoku();
  const aday = path.resolve(kok, goreli);
  const fark = path.relative(kok, aday);
  if (fark.startsWith("..") || path.isAbsolute(fark)) return null;
  try {
    return fs.statSync(aday).isFile() ? aday : null;
  } catch {
    return null;
  }
}

async function arayuzYaniti(request) {
  bootIz(`protocol ${request.url}`);
  let dosya;
  try {
    dosya = guvenliArayuzDosyasi(request.url);
  } catch {
    dosya = null;
  }
  if (!dosya) {
    return new Response("Bulunamadı", { status: 404 });
  }
  // Electron'ın net.fetch Response stream'ini yeniden sarmalamak bazı Chromium
  // sürümlerinde native stream yaşam döngüsü çakışmasına yol açar. CSP, index.html meta
  // etiketiyle uygulanır; dosya yanıtını burada doğrudan döndürürüz.
  return net.fetch(pathToFileURL(dosya).toString());
}

function portBosMu(port) {
  return new Promise((cozumle) => {
    const sunucu = nodeNet.createServer();
    sunucu.once("error", () => cozumle(false));
    sunucu.once("listening", () => sunucu.close(() => cozumle(true)));
    sunucu.listen({ host: "127.0.0.1", port, exclusive: true });
  });
}

async function bosPortSec() {
  for (const port of ADAY_PORTLAR) {
    if (await portBosMu(port)) return port;
  }
  throw new Error(
    `Rasathane motoru için boş port bulunamadı (denenen: ${ADAY_PORTLAR.join(", ")}). ` +
      "Bu portları kullanan uygulamayı kapatıp yeniden deneyin."
  );
}

function sidecarBaslat(port) {
  bootIz(`sidecar başlatılıyor (port ${port})`);
  const exe = sidecarYolu();
  if (!fs.existsSync(exe)) {
    throw new Error(`Rasathane motoru bulunamadı: ${exe}`);
  }

  const logKlasoru = app.getPath("logs");
  fs.mkdirSync(logKlasoru, { recursive: true });
  sidecarLog = fs.createWriteStream(path.join(logKlasoru, "sidecar.log"), { flags: "w" });
  sidecarLog.write(`[gui] sidecar portu: ${port}\n`);
  sidecar = spawn(exe, ["http"], {
    shell: false,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    env: {
      ...process.env,
      RASATHANE_SIDECAR_PORT: String(port),
      RASATHANE_MOTOR_DIR: motorKoku(),
      RASATHANE_SESSION_TOKEN: sessionToken,
      RASATHANE_DATA_DIR: path.join(app.getPath("userData"), "data"),
      YT_CHECKPOINT_DIR: path.join(app.getPath("userData"), "data"),
      // Windows Documents OneDrive'a yönlendirilmiş olabilir; varsayılan analiz
      // çalışma alanı uygulama verisinde kalır. Kullanıcının açık klasör seçimi korunur.
      YT_OUTPUT_BASE: userSettings().workspace || path.join(app.getPath("userData"), "workspace"),
      RASATHANE_LOG_DIR: app.getPath("logs"),
      RASATHANE_WORKER_EXE: path.join(app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "../../infra/dist"), "worker", "rasathane-worker.exe"),
      RASATHANE_NER_MODEL: path.join(packagedModels(), "ner"),
      YT_PIPER_VOICE_DIR: path.join(motorKoku(), "modeller", "piper"),
      RASATHANE_ASR_MODEL: path.join(packagedModels(), "asr"),
      RASATHANE_TYPST_BIN: path.join(app.isPackaged ? process.resourcesPath : path.resolve(__dirname, "../../infra/vendor"), "tooling", "typst", "typst.exe"),
      YT_LLAMACPP_PROFIL: "ram8",
      YT_MOTOR_BACKEND: "llamacpp",
      YT_ALLOW_REMOTE_OLLAMA: "0",
      OLLAMA_HOST: "http://127.0.0.1:11434",
      YT_LLAMACPP_HOST: "http://127.0.0.1:8077",
      YT_LLAMACPP_EMBED_HOST: "http://127.0.0.1:8091",
      YT_MOTOR_KOK: "",
      YT_NER_PYTHON: "",
      YT_ASR_PYTHON: "",
      YT_TTS_PYTHON: "",
      YT_TTS_CLOUD: "0",
      RASATHANE_NATIVE_TTS: "1",
      YT_CLOUD_VERDICT: "0",
    },
  });
  bootIz(`sidecar pid=${sidecar.pid}`);
  sidecar.stdout.on("data", (veri) => sidecarLog?.write(`[stdout] ${veri}`));
  sidecar.stderr.on("data", (veri) => sidecarLog?.write(`[stderr] ${veri}`));
  sidecar.once("error", (hata) => sidecarLog?.write(`[spawn-error] ${hata.stack || hata}\n`));
  sidecar.once("exit", (kod, sinyal) => {
    sidecarLog?.write(`[exit] kod=${kod} sinyal=${sinyal}\n`);
    sidecarLog?.end();
    sidecarLog = null;
    sidecar = null;
  });
}

function sidecarDurdur() {
  if (!sidecar) return;
  kapaniyor = true;
  const cocuk = sidecar;
  sidecar = null;
  const sonuc = spawnSync("taskkill", ["/PID", String(cocuk.pid), "/T", "/F"], {
    shell: false,
    windowsHide: true,
    stdio: "ignore",
  });
  if (sonuc.status !== 0) {
    try {
      cocuk.kill();
    } catch {
      // Süreç zaten kapanmış olabilir.
    }
  }
  sidecarLog?.end();
  sidecarLog = null;
}

async function pencereOlustur(port) {
  bootIz("pencere oluşturuluyor");
  const pencere = new BrowserWindow({
    title: "Rasathane",
    width: 1320,
    height: 880,
    minWidth: 720,
    minHeight: 600,
    show: false,
    // styles.css --zemin ile aynı. Krem bir değer, renderer yüklenene kadar açılışta
    // beyaz flash veriyordu (arayüz koyu: html{color-scheme:dark}).
    backgroundColor: "#0b1712",
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
      spellcheck: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });
  anaPencere = pencere;

  pencere.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  pencere.webContents.on("will-attach-webview", (event) => event.preventDefault());
  pencere.webContents.on("will-navigate", (event, hedef) => {
    if (!hedef.startsWith(`${APP_ORIGIN}/`)) event.preventDefault();
  });
  pencere.once("ready-to-show", () => {
    if (!SMOKE_MODE) pencere.show();
  });
  pencere.on("closed", () => {
    if (anaPencere === pencere) anaPencere = null;
  });

  bootIz("arayüz yükleniyor");
  await pencere.loadURL(`${APP_ORIGIN}/index.html?sidecarPort=${port}`);
  bootIz("arayüz yüklendi");
  return pencere;
}

async function smokeDogrula(pencere) {
  const son = Date.now() + 90_000;
  while (Date.now() < son) {
    const durum = await pencere.webContents.executeJavaScript(`(() => ({
      motor: document.getElementById('motor-cip')?.dataset?.durum || '',
      baslik: document.title,
      kaynakSayisi: document.querySelectorAll('#kaynak-listesi [data-kaynak]').length
    }))()`);
    if (durum.motor === "hazir") {
      if (!durum.baslik.startsWith("Rasathane") || durum.kaynakSayisi !== 6) {
        throw new Error(`Arayüz smoke doğrulaması başarısız: ${JSON.stringify(durum)}`);
      }
      const setup = await pencere.webContents.executeJavaScript(`Promise.race([window.rasathane.setupStatus(), new Promise((_, reject) => setTimeout(() => reject(new Error('Model IPC zaman aşımı')), 190000))])`);
      console.log(JSON.stringify({ smoke: "renderer-ipc", modelReady: setup.ready, modelCount: setup.models.length }));
      if (SMOKE_ANALYSIS) await smokeAnaliz(pencere);
      return;
    }
    if (durum.motor === "hata") throw new Error("Sidecar arayüz tarafından hazır görülemedi.");
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error("Electron smoke doğrulaması zaman aşımına uğradı.");
}

async function smokeAnaliz(pencere) {
  // Açıkça seçilen QA modu: gerçek UI click → preload → owned sidecar → inference.
  // Sabit kamu test sayfası kullanılır; hesap/ödeme veya kişisel içerik gönderilmez.
  const before = await pencere.webContents.executeJavaScript(`window.rasathane.request('/api/rasathane/jobs')`);
  const known = new Set(before.data.items.map(job => job.id));
  await pencere.webContents.executeJavaScript(`(() => {
    document.getElementById('ilk-kurulum')?.close();
    document.getElementById('sekme-analiz').click();
    const input = document.getElementById('url'); input.value = 'https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm'; input.dispatchEvent(new Event('input', { bubbles: true }));
    const button = document.getElementById('analiz-btn'); if (button.disabled) throw new Error('Analiz UI hazır değil'); button.click();
  })()`);
  const deadline = Date.now() + 15 * 60000; let selected;
  while (Date.now() < deadline) {
    if (!selected) {
      const response = await pencere.webContents.executeJavaScript(`window.rasathane.request('/api/rasathane/jobs')`);
      selected = response.data.items.find(job => job.kind === "analysis" && !known.has(job.id));
    }
    if (selected) {
      const response = await pencere.webContents.executeJavaScript(`window.rasathane.request(${JSON.stringify(`/api/rasathane/jobs/${selected.id}`)})`);
      const job = response.data;
      if (["completed", "failed", "cancelled", "interrupted"].includes(job.status)) {
        console.log(JSON.stringify({ smoke: "analysis", jobId: job.id, status: job.status, error: job.error, resultFields: Object.keys(job.result || {}) }));
        if (job.status !== "completed") throw new Error("Gerçek analiz tamamlanamadı.");
        const result = job.result;
        if (result?.transkript_kaynak_dil !== "tr" || result.ceviri_durumu !== "atlandi" ||
            !["cp1254", "windows-1254"].includes(result.quality_provenance?.source?.encoding) ||
            result.quality_provenance?.faithfulness?.independent_verification !== false) {
          throw new Error("Resmî kaynağın encoding/dil/kalite kökeni doğrulanamadı.");
        }
        for (const name of ["03_dokum.docx", "03_dokum.pdf", "04_ozet-sunum.pdf"]) {
          if (!result.artifacts?.some(file => file.name === name && file.bytes > 0 && /^[a-f0-9]{64}$/.test(file.sha256))) {
            throw new Error(`Paketli çıktı makbuzu eksik: ${name}`);
          }
        }
        await smokeArtifact(pencere);
        return;
      }
    }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  throw new Error("Gerçek UI analiz doğrulaması zaman aşımına uğradı.");
}

async function smokeArtifact(pencere) {
  const deadline = Date.now() + 90_000;
  let pdfOpened = false;
  while (Date.now() < deadline) {
    const status = await pencere.webContents.executeJavaScript(`(() => {
      const map = document.getElementById('harita-cerceve');
      const pdf = document.getElementById('izleyici-cerceve');
      return { mapReady: map?.dataset.ready, nodes: Number(map?.dataset.nodes || 0),
        pdfReady: pdf?.dataset.ready, worker: pdf?.dataset.worker,
        pages: Number(pdf?.dataset.pages || 0), page: Number(pdf?.dataset.page || 0),
        canvas: Boolean(pdf?.querySelector('canvas')?.width) };
    })()`);
    if (!pdfOpened && status.mapReady === "true" && status.nodes > 0) {
      await pencere.webContents.executeJavaScript(`(() => {
        const button = [...document.querySelectorAll('#cikti .dosya-ac')].find(item => item.textContent.includes('Sunum'));
        if (!button) throw new Error('PDF önizleme düğmesi yok'); button.click();
      })()`);
      pdfOpened = true;
    }
    if (pdfOpened && status.pdfReady === "true" && status.worker === "ready" && status.pages > 0 && status.canvas) {
      console.log(JSON.stringify({ smoke: "packaged-artifacts", ...status }));
      await pencere.webContents.executeJavaScript(`document.getElementById('izleyici-kapat').click()`);
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error("Paketli harita/PDF worker önizlemesi doğrulanamadı.");
}

const tekOrnek = app.requestSingleInstanceLock();
if (!tekOrnek) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!anaPencere) return;
    if (anaPencere.isMinimized()) anaPencere.restore();
    anaPencere.focus();
  });

  app.whenReady()
    .then(async () => {
      bootIz("app ready");
      prepareMotor();
      account = createAccount({ userData: app.getPath("userData"), safeStorage, openExternal: url => shell.openExternal(url) });
      installBridge();
      await protocol.handle(SCHEME, arayuzYaniti);
      bootIz("protocol hazır");
      session.defaultSession.setPermissionCheckHandler(() => false);
      session.defaultSession.setPermissionRequestHandler((_webContents, _izin, geriDon) => {
        geriDon(false);
      });
      // Renderer yalnız custom protocol assets/blob kullanır. HTTP main'in dar IPC
      // proxy'sinden geçer; HTML preview CSP'sinin geliştirme seam'i ürün ağı açmaz.
      session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*", "ws://*/*", "wss://*/*"] }, (_details, callback) => callback({ cancel: true }));
      const port = await bosPortSec();
      bootIz(`motor portu: ${port}`);
      sidecarPort = port;
      sidecarBaslat(port);
      const pencere = await pencereOlustur(port);
      if (SMOKE_MODE) {
        await smokeDogrula(pencere);
        sidecarDurdur();
        app.exit(0);
      }
    })
    .catch((hata) => {
      sidecarDurdur();
      if (SMOKE_MODE) {
        console.error(hata);
        app.exit(1);
        return;
      }
      dialog.showErrorBox("Rasathane başlatılamadı", String(hata?.stack || hata));
      app.quit();
    });

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) void pencereOlustur(sidecarPort);
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", () => { account?.close(); sidecarDurdur(); });
  app.on("will-quit", sidecarDurdur);
  process.on("exit", sidecarDurdur);
}

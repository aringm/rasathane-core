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
const { createAuthGate } = require("./auth-gate.cjs");
const { conservativeSearchClaims } = require("./smoke-evidence.cjs");

const SCHEME = "rasathane";
const APP_ORIGIN = `${SCHEME}://app`;
const SMOKE_MODE = process.argv.includes("--smoke-test");
const SMOKE_ANALYSIS = SMOKE_MODE && process.argv.includes("--smoke-analysis");
const SMOKE_PRODUCT = SMOKE_MODE && process.argv.includes("--smoke-product");
const SMOKE_GENERIC = SMOKE_ANALYSIS && process.argv.includes("--smoke-generic");
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
let authGate;

function userSettings() {
  try { return JSON.parse(fs.readFileSync(path.join(app.getPath("userData"), "desktop-settings.json"), "utf8")); }
  catch { return {}; }
}

let sidecarSessionUpdates = Promise.resolve();
function configureSidecarSession(accessToken, lease = null) {
  const update = sidecarSessionUpdates.catch(() => {}).then(async () => {
    lease?.assertCurrent();
    const response = await fetch(`http://127.0.0.1:${sidecarPort}/api/product/service-session`, {
      method: "POST", redirect: "error", signal: lease ? AbortSignal.any([lease.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(5000),
      headers: { "Content-Type": "application/json", Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken }, body: JSON.stringify({ access_token: accessToken }),
    });
    await response.body?.cancel();
    if (!response.ok) throw new Error("Hesap bağlantısı yerel motora aktarılamadı.");
    lease?.assertCurrent();
  });
  sidecarSessionUpdates = update;
  return update;
}
async function clearSidecarSession() {
  try { await configureSidecarSession(null); } catch { /* sidecar kapalıysa bellek de yoktur */ }
}

function installBridge() {
  function check(event) {
    if (!trustedSender(event, anaPencere)) throw new Error("İstek kaynağı izinli değil.");
  }
  const protectedHandle = (channel, handler) => ipcMain.handle(channel, (event, ...args) => {
    check(event); return authGate.run(lease => handler(lease, event, ...args));
  });
  protectedHandle("rasathane:request", async (lease, event, route, options) => {
    check(event);
    const request = validateRequest(route, options);
    // Hosted kaynak takibi için token yalnız main → loopback belleğine geçer.
    // Renderer allowlist bu dahili endpoint'i içermez; token JSON response'a girmez.
    {
      const accessToken = await account.serviceAccessToken();
      lease.assertCurrent();
      await configureSidecarSession(accessToken, lease);
    }
    const controller = new AbortController();
    const bulletinSpeech = /^\/api\/rasathane\/bulletins\/[a-zA-Z0-9_-]+\/speech$/.test(request.route);
    const timer = setTimeout(() => controller.abort(), bulletinSpeech ? 210000 : 120000);
    try {
      const response = await fetch(`http://127.0.0.1:${sidecarPort}${request.route}`, {
        method: request.method, body: request.body, redirect: "error", signal: AbortSignal.any([controller.signal, lease.signal]),
        headers: { "Content-Type": "application/json", Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken },
      });
      const cap = (bulletinSpeech ? 32 : 8) * 1024 * 1024;
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
  protectedHandle("rasathane:select-workspace", async (lease, event) => {
    check(event);
    const result = await dialog.showOpenDialog(anaPencere, { title: "Rasathane analiz çıktı klasörü", properties: ["openDirectory", "createDirectory"] });
    lease.assertCurrent();
    if (result.canceled || !result.filePaths[0]) return { cancelled: true };
    const selected = path.resolve(result.filePaths[0]);
    const settingsPath = path.join(app.getPath("userData"), "desktop-settings.json");
    fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
    fs.writeFileSync(`${settingsPath}.tmp`, JSON.stringify({ ...userSettings(), workspace: selected }, null, 2), { encoding: "utf8", mode: 0o600 });
    fs.renameSync(`${settingsPath}.tmp`, settingsPath);
    return { cancelled: false, path: selected, restartRequired: true };
  });
  protectedHandle("rasathane:export-data", async (lease, event) => {
    check(event);
    const choice = await dialog.showSaveDialog(anaPencere, { title: "Rasathane verisini dışa aktar", defaultPath: path.join(app.getPath("documents"), "rasathane-arsiv.json"), filters: [{ name: "JSON", extensions: ["json"] }] });
    lease.assertCurrent();
    if (choice.canceled || !choice.filePath) return { cancelled: true };
    const file = path.resolve(choice.filePath); const temporary = `${file}.${crypto.randomBytes(8).toString("hex")}.partial`;
    let handle;
    try {
      await configureSidecarSession(await account.serviceAccessToken(), lease);
      const response = await fetch(`http://127.0.0.1:${sidecarPort}/api/rasathane/export`, { redirect: "error", signal: AbortSignal.any([lease.signal, AbortSignal.timeout(120000)]), headers: { Origin: APP_ORIGIN, "X-Rasathane-Session": sessionToken } });
      if (!response.ok || !response.body || !response.headers.get("content-type")?.includes("application/json")) throw new Error("Dışa aktarma yanıtı alınamadı.");
      lease.assertCurrent();
      handle = await fs.promises.open(temporary, "wx", 0o600); let bytes = 0; const hash = crypto.createHash("sha256");
      for await (const chunk of response.body) { lease.assertCurrent(); bytes += chunk.length; if (bytes > 256 * 1024 * 1024) throw new Error("Dışa aktarma boyutu 256 MB sınırını aştı. Yerel veritabanının yedeğiyle arşivi koruyabilirsiniz."); hash.update(chunk); await handle.writeFile(chunk); }
      await handle.sync(); await handle.close(); handle = null; lease.assertCurrent(); await fs.promises.rename(temporary, file);
      return { saved: true, path: file, bytes, sha256: hash.digest("hex") };
    } finally { if (handle) await handle.close(); if (fs.existsSync(temporary)) await fs.promises.unlink(temporary); }
  });
  ipcMain.handle("rasathane:open-account", async event => {
    check(event); return account.start();
  });
  ipcMain.handle("rasathane:send-login-code", (event, email) => { check(event); return account.sendLoginCode(email); });
  ipcMain.handle("rasathane:verify-login-code", (event, code) => { check(event); return account.verifyLoginCode(code); });
  ipcMain.handle("rasathane:cancel-login", event => { check(event); return account.cancelLogin(); });
  ipcMain.handle("rasathane:open-login-document", async (event, document) => {
    check(event);
    if (!["terms", "privacy"].includes(document)) throw new Error("Belge seçimi geçersiz.");
    await shell.openExternal(`https://www.muhakeme.ai/${document === "terms" ? "kosullar" : "kvkk"}`);
    return { opened: true };
  });
  ipcMain.handle("rasathane:account-status", event => { check(event); return account.checkSession(); });
  ipcMain.handle("rasathane:entitlement", async event => { check(event); return account.entitlement(); });
  ipcMain.handle("rasathane:start-trial", async event => { check(event); return account.startTrial(); });
  ipcMain.handle("rasathane:sign-out", async event => {
    check(event); return account.signOut();
  });
  protectedHandle("rasathane:setup-status", async (lease, event) => {
    check(event); bootIz("model kontrolü başladı");
    const result = await modelSetup.inspect(); bootIz(`model kontrolü bitti: ${result.ready}`); return result;
  });
  protectedHandle("rasathane:open-source", async (lease, event, url) => { check(event); await shell.openExternal(publicSourceURL(url)); return { opened: true }; });
  protectedHandle("rasathane:install-models", async (lease, event) => { check(event); return modelSetup.start(); });
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
  const initialAccount = await account.checkSession();
  if ((SMOKE_ANALYSIS || SMOKE_PRODUCT) && initialAccount.state !== "signed_in") throw new Error("Ürün/analiz smoke testi için doğrulanmış Muhakeme girişi gerekli; test modu giriş zorunluluğunu kaldırmaz.");
  const son = Date.now() + 90_000;
  while (Date.now() < son) {
    const durum = await pencere.webContents.executeJavaScript(`(() => ({
      motor: document.getElementById('motor-cip')?.dataset?.durum || '',
      locked: document.body.classList.contains('session-locked'),
      loginVisible: document.getElementById('giris-ekrani')?.hidden === false,
      privateInert: [...document.querySelectorAll('.topbar,.app-sidebar,#app-main,.app-skip')].every(node => node.inert),
      baslik: document.title,
      kaynakSayisi: document.querySelectorAll('#kaynak-listesi [data-kaynak]').length
    }))()`);
    if (initialAccount.state !== "signed_in" && durum.locked && durum.loginVisible && durum.privateInert) {
      const rejected = await pencere.webContents.executeJavaScript(`(async () => {
        const actions = [
          () => window.rasathane.request('/api/rasathane/state'),
          () => window.rasathane.setupStatus(),
          () => window.rasathane.installModels(),
          () => window.rasathane.selectWorkspace(),
          () => window.rasathane.exportData(),
          () => window.rasathane.openSource('https://www.resmigazete.gov.tr/'),
        ];
        const results = await Promise.allSettled(actions.map(action => action()));
        return results.map(result => result.status === 'rejected' && String(result.reason?.message).includes('giriş gerekli'));
      })()`);
      if (!durum.baslik.startsWith("Rasathane") || rejected.length !== 6 || rejected.some(value => !value)) throw new Error("Girişsiz ürün IPC engeli doğrulanamadı.");
      console.log(JSON.stringify({ smoke: "renderer-login-lock", authenticated: false, privateScreensInert: true, blockedOperations: rejected.length }));
      return;
    }
    if (durum.motor === "hazir" && initialAccount.state === "signed_in") {
      if (!durum.baslik.startsWith("Rasathane") || durum.kaynakSayisi !== 6) {
        throw new Error(`Arayüz smoke doğrulaması başarısız: ${JSON.stringify(durum)}`);
      }
      const setup = await pencere.webContents.executeJavaScript(`Promise.race([window.rasathane.setupStatus(), new Promise((_, reject) => setTimeout(() => reject(new Error('Model IPC zaman aşımı')), 190000))])`);
      console.log(JSON.stringify({ smoke: "renderer-ipc", modelReady: setup.ready, modelCount: setup.models.length }));
      if (SMOKE_PRODUCT) await require("./smoke-product-ui.cjs").verifyProductUI(pencere);
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
  const sourceURL = SMOKE_GENERIC
    ? "https://arxiv.org/abs/1706.03762"
    : "https://www.resmigazete.gov.tr/eskiler/2026/10/20261003-1.htm";
  await pencere.webContents.executeJavaScript(`(() => {
    document.getElementById('ilk-kurulum')?.close();
    document.getElementById('sekme-analiz').click();
    const input = document.getElementById('url'); input.value = ${JSON.stringify(sourceURL)}; input.dispatchEvent(new Event('input', { bubbles: true }));
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
        if (SMOKE_GENERIC) {
          const source = result.quality_provenance?.source;
          const summary = result.quality_provenance?.summary;
          const claims = result.factcheck_iddialar;
          if (result?.stub !== false || result.cloud_cagrisi_sayisi !== 0 ||
              result.kaynak_turu !== "arxiv" || !(result.ozet_detay || "").trim() ||
              result.analysis_mode !== "model_analysis" ||
              source?.text_scope !== "abstract_only" || source.full_text_fetched !== false ||
              !/^[a-f0-9]{64}$/.test(source.original_text_sha256 || "") ||
              summary?.method !== "source_sentence_selection_and_model_summary" ||
              summary.layers?.kisa !== "translated_source_sentences" ||
              summary.layers?.orta !== "translated_source_sentences" ||
              !conservativeSearchClaims(claims)) {
            throw new Error("Genel kaynak yerel analiz yolu doğrulanamadı.");
          }
        } else if (result?.transkript_kaynak_dil !== "tr" || result.ceviri_durumu !== "atlandi" ||
            !["cp1254", "windows-1254"].includes(result.quality_provenance?.source?.encoding) ||
            result.quality_provenance?.faithfulness?.independent_verification !== false ||
            result.analysis_mode !== "source_extracts" || result.ozet_faithfulness !== null ||
            result.factcheck_durum !== "atlandi_resmi_kaynak" || !result.factcheck_reason) {
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
        canvas: Boolean(pdf?.querySelector('canvas')?.width),
        summaryHeading: document.getElementById('ozet-baslik')?.textContent,
        summaryMethod: document.getElementById('ozet-model-not')?.textContent,
        factcheckSummary: document.getElementById('factcheck-ozet')?.textContent,
        sourceReason: document.getElementById('factcheck-liste')?.textContent };
    })()`);
    if (!pdfOpened && status.mapReady === "true" && status.nodes > 0) {
      await pencere.webContents.executeJavaScript(`(() => {
        const button = [...document.querySelectorAll('#cikti .dosya-ac')].find(item => item.textContent.includes('Sunum'));
        if (!button) throw new Error('PDF önizleme düğmesi yok'); button.click();
      })()`);
      pdfOpened = true;
    }
    if (pdfOpened && status.pdfReady === "true" && status.worker === "ready" && status.pages > 0 && status.canvas) {
      if (!SMOKE_GENERIC && (status.summaryHeading !== "Birincil metinden okuma özeti" || !status.sourceReason?.trim())) {
        throw new Error("Birincil kaynak okuma yöntemi arayüzde açıklanmadı.");
      }
      if (SMOKE_GENERIC && (status.summaryHeading !== "Yayın özeti (abstract) analizi" ||
          !status.summaryMethod?.includes("tam makale okunmadı") ||
          !status.factcheckSummary?.includes("0 destekleniyor · 0 çelişiyor"))) {
        throw new Error("Abstract kapsamı ve bağımsız doğrulama sınırı arayüzde açıklanmadı.");
      }
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
      authGate = createAuthGate(account);
      account.subscribe(state => {
        if (anaPencere && !anaPencere.isDestroyed()) anaPencere.webContents.send("rasathane:account-change", state);
        if (state.state === "signed_in") {
          void authGate.run(async lease => configureSidecarSession(await account.serviceAccessToken(), lease)).catch(() => {});
        } else {
          modelSetup.cancel();
          void clearSidecarSession();
        }
      });
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
  app.on("before-quit", () => { authGate?.close(); account?.close(); modelSetup?.cancel(); sidecarDurdur(); });
  app.on("will-quit", sidecarDurdur);
  process.on("exit", sidecarDurdur);
}

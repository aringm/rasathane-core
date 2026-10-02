"use strict";
const crypto = require("node:crypto");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const AUTH_ORIGIN = "https://www.muhakeme.ai";
const CLIENT_ID = "rasathane-desktop";

function pkcePair() {
  const verifier = crypto.randomBytes(32).toString("base64url");
  return { verifier, challenge: crypto.createHash("sha256").update(verifier).digest("base64url"), state: crypto.randomBytes(32).toString("base64url") };
}
function validSession(record, deviceId) {
  return record?.schema_version === "1.1" && record.device_id === deviceId && record.durum === "aktif" &&
    /^dses_[a-f0-9]{16}$/.test(record.session_id || "") && /^at_[A-Za-z0-9_-]{43}$/.test(record.access_token || "") &&
    /^rt_[A-Za-z0-9_-]{43}$/.test(record.refresh_token || "") && Array.isArray(record.scope) &&
    record.scope.includes("desktop") && record.scope.includes("urun:rasathane") &&
    record.scope.every(value => ["desktop", "urun:rasathane"].includes(value)) &&
    Number.isFinite(Date.parse(record.access_sure_sonu)) && Number.isFinite(Date.parse(record.refresh_sure_sonu));
}
function createAccount({ userData, safeStorage, openExternal, transport = fetch }) {
  const file = path.join(userData, "account.enc");
  const deviceFile = path.join(userData, "device.json");
  fs.mkdirSync(userData, { recursive: true });
  let deviceId;
  try { deviceId = JSON.parse(fs.readFileSync(deviceFile, "utf8")).deviceId; } catch { /* ilk kullanım */ }
  if (!/^dev_[a-f0-9]{32}$/.test(deviceId || "")) { deviceId = `dev_${crypto.randomBytes(16).toString("hex")}`; fs.writeFileSync(deviceFile, JSON.stringify({ deviceId })); }
  let session = null; let status = "signed_out"; let error = null; let pendingServer = null; let pendingTimer = null; let epoch = 0; let refreshing = null;
  if (safeStorage.isEncryptionAvailable()) {
    try { const candidate = JSON.parse(safeStorage.decryptString(fs.readFileSync(file))); if (validSession(candidate, deviceId)) { session = candidate; status = "signed_in"; } } catch { /* geçersiz/başka kullanıcı token'ı kullanılmaz */ }
  }
  function closePending() { if (pendingServer) pendingServer.close(); pendingServer = null; if (pendingTimer) clearTimeout(pendingTimer); pendingTimer = null; }
  function clearSession() { epoch++; session = null; status = "signed_out"; if (fs.existsSync(file)) fs.unlinkSync(file); }
  function save(record) {
    if (!safeStorage.isEncryptionAvailable()) throw new Error("Windows güvenli token deposu kullanılamıyor.");
    if (!validSession(record, deviceId)) throw new Error("Hesap oturumu Rasathane sözleşmesiyle uyumlu değil.");
    fs.writeFileSync(`${file}.tmp`, safeStorage.encryptString(JSON.stringify(record)), { mode: 0o600 }); fs.renameSync(`${file}.tmp`, file);
    session = record; status = "signed_in"; error = null;
  }
  async function api(route, body, bearer) {
    const response = await transport(`${AUTH_ORIGIN}${route}`, { method: body ? "POST" : "GET", redirect: "error", signal: AbortSignal.timeout(20000),
      headers: { "Content-Type": "application/json", ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) }, body: body ? JSON.stringify(body) : undefined });
    if (Number(response.headers.get("content-length")) > 65536) throw new Error("Hesap yanıtı çok büyük.");
    if (response.status === 204) return null;
    const chunks = []; let size = 0;
    if (response.body) for await (const chunk of response.body) { size += chunk.length; if (size > 65536) { await response.body.cancel().catch(() => {}); throw new Error("Hesap yanıtı çok büyük."); } chunks.push(Buffer.from(chunk)); }
    let data = null; try { data = JSON.parse(Buffer.concat(chunks).toString("utf8")); } catch { /* hata sayfası token veya içerik olarak geri verilmez */ }
    if (!response.ok) {
      const problem = new Error(`Muhakeme hesabı isteği başarısız (${response.status}).`); problem.status = response.status; problem.code = data?.kod || data?.code || data?.error?.code;
      throw problem;
    }
    if (!data) throw new Error("Muhakeme hesabı yanıtı geçersiz."); return data;
  }
  async function accessToken() {
    if (!session || Date.parse(session.refresh_sure_sonu) <= Date.now()) { clearSession(); throw new Error("Muhakeme hesabına giriş gerekli."); }
    if (Date.parse(session.access_sure_sonu) <= Date.now() + 30000) {
      if (!refreshing) {
        const generation = epoch; const token = session.refresh_token;
        const task = (async () => {
          try {
            const record = await api("/api/auth/device/refresh", { refresh_token: token, device_id: deviceId });
            if (generation !== epoch) throw new Error("Hesap oturumu kapatıldı."); save(record);
          } catch (problem) { if (generation === epoch && [401, 403].includes(problem.status)) clearSession(); throw problem; }
        })();
        refreshing = task; task.finally(() => { if (refreshing === task) refreshing = null; }).catch(() => {});
      }
      await refreshing;
    }
    if (!session) throw new Error("Muhakeme hesabına giriş gerekli.");
    return session.access_token;
  }
  async function authorized(route, body) {
    const generation = epoch;
    try { return await api(route, body, await accessToken()); }
    catch (problem) {
      if (problem.status === 401 && generation === epoch) clearSession();
      throw problem;
    }
  }
  async function start() {
    if (pendingServer) return { started: true };
    if (!safeStorage.isEncryptionAvailable()) throw new Error("Windows güvenli token deposu kullanılamıyor.");
    const pair = pkcePair(); let redirectURI; let exchanged = false; const generation = ++epoch;
    status = "waiting"; error = null;
    pendingServer = http.createServer(async (request, response) => {
      let callback;
      try { if (!request.url?.startsWith("/")) throw new Error(); callback = new URL(request.url, redirectURI); }
      catch { response.writeHead(400); response.end("Gecersiz hesap donusu."); return; }
      if (request.method !== "GET" || callback.pathname !== "/cihaz/geri-donus" || callback.searchParams.get("state") !== pair.state || exchanged) { response.writeHead(400); response.end("Gecersiz hesap donusu."); return; }
      if (callback.searchParams.has("error")) {
        if (generation === epoch) { status = session ? "signed_in" : "signed_out"; error = "Hesap bağlantısı iptal edildi."; closePending(); }
        response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }); response.end("Hesap bağlantısı iptal edildi. Rasathane'ye dönebilirsiniz."); return;
      }
      const code = callback.searchParams.get("code");
      if (!/^dc_[A-Za-z0-9_-]{43}$/.test(code || "")) { response.writeHead(400); response.end("Yetkilendirme kodu eksik."); return; }
      exchanged = true;
      try {
        const record = await api("/api/auth/device/exchange", { client_id: CLIENT_ID, code, code_verifier: pair.verifier, device_id: deviceId, redirect_uri: redirectURI });
        if (generation !== epoch) throw new Error("Hesap bağlantısı iptal edildi."); save(record);
        response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }); response.end("Rasathane hesabı bağlandı. Uygulamaya dönebilirsiniz.");
      } catch (problem) { if (generation === epoch) { error = String(problem.message); status = "failed"; } response.writeHead(502); response.end("Hesap baglanamadi. Rasathane'de yeniden deneyin."); }
      finally { if (generation === epoch) closePending(); }
    });
    try { await new Promise((resolve, reject) => { pendingServer.once("error", reject); pendingServer.listen(0, "127.0.0.1", resolve); }); }
    catch (problem) { closePending(); status = "failed"; error = "Hesap dönüş bağlantısı açılamadı."; throw problem; }
    const address = pendingServer.address(); redirectURI = `http://127.0.0.1:${address.port}/cihaz/geri-donus`;
    const url = new URL("/hesap/cihaz-yetkilendir", AUTH_ORIGIN);
    for (const [key, value] of Object.entries({ response_type: "code", client_id: CLIENT_ID, scope: "desktop", redirect_uri: redirectURI, code_challenge: pair.challenge, code_challenge_method: "S256", state: pair.state, device_id: deviceId })) url.searchParams.set(key, value);
    pendingTimer = setTimeout(() => { closePending(); if (status === "waiting") { status = "failed"; error = "Hesap bağlantısı zaman aşımına uğradı. Yeniden deneyin."; } }, 300000); pendingTimer.unref();
    try { await openExternal(url.href); } catch (problem) { closePending(); status = "failed"; error = String(problem.message); throw problem; }
    return { started: true };
  }
  return {
    start, close: closePending,
    status: () => ({ state: status, error, scope: session?.scope || [] }),
    entitlement: async () => authorized("/api/lisans/v2/durum"),
    startTrial: async () => authorized("/api/lisans/v2/deneme", { urun: "rasathane", idempotency_key: crypto.randomUUID() }),
    serviceAccessToken: accessToken, // yalnız main; preload ve renderer'a açılmaz
    signOut: async () => { const token = session?.access_token; closePending(); clearSession(); let remoteRevoked = !token; try { if (token) { await api("/api/auth/device/revoke", {}, token); remoteRevoked = true; } } catch { /* yerel çıkış tamamlanır; ağ hatası token'ı diskte bırakmaz */ } return { signedOut: true, remoteRevoked }; },
  };
}
module.exports = { createAccount, validSession, pkcePair };

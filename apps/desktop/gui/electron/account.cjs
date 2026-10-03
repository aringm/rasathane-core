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
  let session = null; let status = "signed_out"; let error = null; let pendingServer = null; let pendingTimer = null; let epoch = 0; let refreshing = null; const listeners = new Set(); let expiryTimer = null;
  let pendingEmail = null; let errorCode = null; let emailMode = false;
  if (safeStorage.isEncryptionAvailable()) {
    try { const candidate = JSON.parse(safeStorage.decryptString(fs.readFileSync(file))); if (validSession(candidate, deviceId) && Date.parse(candidate.refresh_sure_sonu) > Date.now()) { session = candidate; status = Date.parse(candidate.access_sure_sonu) > Date.now() ? "signed_in" : "expired"; } } catch { /* geçersiz/başka kullanıcı token'ı kullanılmaz */ }
  }
  function snapshot() {
    return { state: status, error, scope: status === "signed_in" ? [...(session?.scope || [])] : [], ...(emailMode ? { errorCode, login: pendingEmail ? { email: pendingEmail.email, expiresAt: pendingEmail.expiresAt, resendAt: pendingEmail.resendAt } : null } : {}) };
  }
  function publish() { const value = snapshot(); for (const listener of listeners) listener(value); }
  function scheduleExpiry() {
    if (expiryTimer) clearTimeout(expiryTimer);
    expiryTimer = null;
    if (!session) return;
    const remaining = Math.min(Date.parse(session.access_sure_sonu), Date.parse(session.refresh_sure_sonu)) - Date.now();
    if (remaining <= 0) { if (Date.parse(session.refresh_sure_sonu) <= Date.now()) clearSession(); else { status = "expired"; publish(); } return; }
    expiryTimer = setTimeout(() => { status = "expired"; publish(); }, Math.min(remaining, 2147483647)); expiryTimer.unref();
  }
  function closePending() { if (pendingServer) pendingServer.close(); pendingServer = null; if (pendingTimer) clearTimeout(pendingTimer); pendingTimer = null; }
  function clearSession() { epoch++; pendingEmail = null; error = null; errorCode = null; session = null; status = "signed_out"; if (expiryTimer) clearTimeout(expiryTimer); expiryTimer = null; if (fs.existsSync(file)) fs.unlinkSync(file); publish(); }
  function save(record) {
    if (!safeStorage.isEncryptionAvailable()) throw new Error("Windows güvenli token deposu kullanılamıyor.");
    if (!validSession(record, deviceId)) throw new Error("Hesap oturumu Rasathane sözleşmesiyle uyumlu değil.");
    fs.writeFileSync(`${file}.tmp`, safeStorage.encryptString(JSON.stringify(record)), { mode: 0o600 }); fs.renameSync(`${file}.tmp`, file);
    session = record; pendingEmail = null; status = "signed_in"; error = null; errorCode = null; scheduleExpiry(); publish();
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
      const retryAfter = Number(response.headers.get("retry-after")); problem.retryAfter = Number.isFinite(retryAfter) && retryAfter > 0 ? Math.min(Math.ceil(retryAfter), 3600) : 60;
      throw problem;
    }
    if (!data) throw new Error("Muhakeme hesabı yanıtı geçersiz."); return data;
  }
  async function accessToken() {
    if (!session || !["signed_in", "expired"].includes(status)) throw new Error("Muhakeme hesabına giriş gerekli.");
    if (Date.parse(session.refresh_sure_sonu) <= Date.now()) { clearSession(); throw new Error("Muhakeme hesabına giriş gerekli."); }
    if (Date.parse(session.access_sure_sonu) <= Date.now() && status === "signed_in") { status = "expired"; publish(); }
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
    try { const result = await api(route, body, await accessToken()); if (generation !== epoch) throw new Error("Hesap oturumu kapatıldı."); return result; }
    catch (problem) {
      if (problem.status === 401 && generation === epoch) clearSession();
      throw problem;
    }
  }
  async function start() {
    pendingEmail = null; emailMode = false; errorCode = null;
    if (pendingServer) return { started: true };
    if (!safeStorage.isEncryptionAvailable()) throw new Error("Windows güvenli token deposu kullanılamıyor.");
    const pair = pkcePair(); let redirectURI; let exchanged = false; const generation = ++epoch;
    status = "waiting"; error = null; publish();
    pendingServer = http.createServer(async (request, response) => {
      let callback;
      try { if (!request.url?.startsWith("/")) throw new Error(); callback = new URL(request.url, redirectURI); }
      catch { response.writeHead(400); response.end("Gecersiz hesap donusu."); return; }
      if (request.method !== "GET" || callback.pathname !== "/cihaz/geri-donus" || callback.searchParams.get("state") !== pair.state || exchanged) { response.writeHead(400); response.end("Gecersiz hesap donusu."); return; }
      if (callback.searchParams.has("error")) {
        if (generation === epoch) { status = session ? (Date.parse(session.access_sure_sonu) > Date.now() && Date.parse(session.refresh_sure_sonu) > Date.now() ? "signed_in" : "expired") : "signed_out"; error = "Hesap bağlantısı iptal edildi."; closePending(); publish(); }
        response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }); response.end("Hesap bağlantısı iptal edildi. Rasathane'ye dönebilirsiniz."); return;
      }
      const code = callback.searchParams.get("code");
      if (!/^dc_[A-Za-z0-9_-]{43}$/.test(code || "")) { response.writeHead(400); response.end("Yetkilendirme kodu eksik."); return; }
      exchanged = true;
      try {
        const record = await api("/api/auth/device/exchange", { client_id: CLIENT_ID, code, code_verifier: pair.verifier, device_id: deviceId, redirect_uri: redirectURI });
        if (generation !== epoch) throw new Error("Hesap bağlantısı iptal edildi."); save(record);
        response.writeHead(200, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" }); response.end("Rasathane hesabı bağlandı. Uygulamaya dönebilirsiniz.");
      } catch (problem) { if (generation === epoch) { error = String(problem.message); status = "failed"; publish(); } response.writeHead(502); response.end("Hesap baglanamadi. Rasathane'de yeniden deneyin."); }
      finally { if (generation === epoch) closePending(); }
    });
    try { await new Promise((resolve, reject) => { pendingServer.once("error", reject); pendingServer.listen(0, "127.0.0.1", resolve); }); }
    catch (problem) { closePending(); status = "failed"; error = "Hesap dönüş bağlantısı açılamadı."; publish(); throw problem; }
    const address = pendingServer.address(); redirectURI = `http://127.0.0.1:${address.port}/cihaz/geri-donus`;
    const url = new URL("/hesap/cihaz-yetkilendir", AUTH_ORIGIN);
    for (const [key, value] of Object.entries({ response_type: "code", client_id: CLIENT_ID, scope: "desktop", redirect_uri: redirectURI, code_challenge: pair.challenge, code_challenge_method: "S256", state: pair.state, device_id: deviceId })) url.searchParams.set(key, value);
    pendingTimer = setTimeout(() => { closePending(); if (status === "waiting") { status = "failed"; error = "Hesap bağlantısı zaman aşımına uğradı. Yeniden deneyin."; publish(); } }, 300000); pendingTimer.unref();
    try { await openExternal(url.href); } catch (problem) { closePending(); status = "failed"; error = String(problem.message); publish(); throw problem; }
    return { started: true };
  }
  function loginError(code, message, nextState = "failed") {
    errorCode = code; error = message; status = nextState; publish(); return snapshot();
  }
  function emailFailure(problem, verifying) {
    const waiting = pendingEmail?.challengeId && Date.parse(pendingEmail.expiresAt) > Date.now();
    if (problem.code === "OTP_GECERSIZ") return loginError("wrong_code", "Doğrulama kodu yanlış. E-postanıza gelen 6 haneli kodu yeniden girin.", waiting ? "code_sent" : "failed");
    if (["OTP_SURESI_DOLDU", "OTP_DENEME_SINIRI"].includes(problem.code)) {
      if (pendingEmail) { pendingEmail.challengeId = null; pendingEmail.verifier = null; pendingEmail.expiresAt = new Date().toISOString(); }
      return loginError("expired_code", problem.code === "OTP_DENEME_SINIRI" ? "Kod deneme sınırına ulaşıldı. Yeni bir kod isteyin." : "Kodun süresi doldu. Yeni bir kod isteyin.");
    }
    if (problem.status === 429 || problem.code === "HIZ_SINIRI") {
      if (pendingEmail) { pendingEmail.resendAt = new Date(Date.now() + (problem.retryAfter || 60) * 1000).toISOString(); if (verifying) pendingEmail.verifyAfter = pendingEmail.resendAt; }
      return loginError("rate_limited", "Çok sık deneme yapıldı. Sayaç tamamlandığında yeniden deneyin.", waiting ? "code_sent" : "failed");
    }
    if (["EMAIL_INVALID", "EMAIL_DISPOSABLE"].includes(problem.code)) return loginError("invalid_email", problem.code === "EMAIL_DISPOSABLE" ? "Geçici e-posta adresi kullanılamıyor. Kalıcı e-posta adresinizi girin." : "Geçerli bir e-posta adresi girin.");
    return loginError("unavailable", verifying ? "Giriş tamamlanamadı. Bağlantınızı kontrol ederek yeniden deneyin." : "Doğrulama kodu gönderilemedi. Biraz sonra yeniden deneyin.", waiting ? "code_sent" : "failed");
  }
  async function sendLoginCode(value) {
    emailMode = true;
    if (["sending_code", "verifying_code"].includes(status)) return snapshot();
    if (status === "signed_in") return snapshot();
    if (typeof value !== "string" || value.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())) return loginError("invalid_email", "Geçerli bir e-posta adresi girin.");
    const email = value.trim().toLowerCase();
    if (pendingEmail && Date.parse(pendingEmail.resendAt) > Date.now()) return loginError("rate_limited", "Yeni kod istemek için sayaç tamamlanana kadar bekleyin.", pendingEmail.challengeId ? "code_sent" : "failed");
    if (!safeStorage.isEncryptionAvailable()) return loginError("secure_storage", "Windows güvenli oturum deposu kullanılamıyor.");
    closePending(); clearSession(); const generation = epoch; const pair = pkcePair();
    pendingEmail = { email, verifier: pair.verifier, challengeId: null, expiresAt: null, resendAt: null };
    status = "sending_code"; error = null; errorCode = null; publish();
    try {
      const result = await api("/api/auth/device/email/request", { client_id: CLIENT_ID, email, device_id: deviceId, code_challenge: pair.challenge, code_challenge_method: "S256" });
      if (generation !== epoch) return snapshot();
      if (!/^eotp_[A-Za-z0-9_-]{43}$/.test(result.challenge_id || "") || !Number.isFinite(Date.parse(result.expires_at)) || Date.parse(result.expires_at) <= Date.now() || Date.parse(result.expires_at) > Date.now() + 3600000 || !Number.isInteger(result.resend_after_seconds) || result.resend_after_seconds < 0 || result.resend_after_seconds > 3600) throw new Error("invalid challenge");
      pendingEmail.challengeId = result.challenge_id; pendingEmail.expiresAt = result.expires_at; pendingEmail.resendAt = new Date(Date.now() + result.resend_after_seconds * 1000).toISOString();
      status = "code_sent"; publish(); return snapshot();
    } catch (problem) { if (generation !== epoch) return snapshot(); return emailFailure(problem, false); }
  }
  async function verifyLoginCode(code) {
    emailMode = true;
    if (["sending_code", "verifying_code"].includes(status) || status === "signed_in") return snapshot();
    if (!pendingEmail?.challengeId || Date.parse(pendingEmail.expiresAt) <= Date.now()) return loginError("expired_code", "Kodun süresi doldu. Yeni bir kod isteyin.");
    if (Date.parse(pendingEmail.verifyAfter) > Date.now()) return loginError("rate_limited", "Çok sık deneme yapıldı. Sayaç tamamlandığında yeniden deneyin.", "code_sent");
    if (typeof code !== "string" || !/^\d{6}$/.test(code)) return loginError("wrong_code", "E-postanıza gelen 6 haneli kodu girin.", "code_sent");
    const generation = epoch; const input = pendingEmail;
    status = "verifying_code"; error = null; errorCode = null; publish();
    try {
      const record = await api("/api/auth/device/email/verify", { client_id: CLIENT_ID, email: input.email, device_id: deviceId, challenge_id: input.challengeId, code, code_verifier: input.verifier });
      if (generation !== epoch) return snapshot();
      if (Date.parse(record.access_sure_sonu) <= Date.now() || Date.parse(record.refresh_sure_sonu) <= Date.now()) throw new Error("expired session");
      save(record); return snapshot();
    } catch (problem) { if (generation !== epoch) return snapshot(); return emailFailure(problem, true); }
  }
  function cancelLogin() {
    epoch++; closePending(); pendingEmail = null; error = null; errorCode = null; emailMode = true;
    status = session ? (Date.parse(session.access_sure_sonu) > Date.now() && Date.parse(session.refresh_sure_sonu) > Date.now() ? "signed_in" : "expired") : "signed_out";
    publish(); return snapshot();
  }
  scheduleExpiry();
  function current(generation) {
    return generation === epoch && status === "signed_in" && !!session && Date.parse(session.access_sure_sonu) > Date.now() && Date.parse(session.refresh_sure_sonu) > Date.now();
  }
  return {
    start, sendLoginCode, verifyLoginCode, cancelLogin, close: () => { epoch++; pendingEmail = null; closePending(); if (expiryTimer) clearTimeout(expiryTimer); listeners.clear(); },
    status: () => { if (session && Date.parse(session.refresh_sure_sonu) <= Date.now()) clearSession(); else if (session && Date.parse(session.access_sure_sonu) <= Date.now() && status === "signed_in") { status = "expired"; publish(); } return snapshot(); },
    checkSession: async () => { if (session && ["signed_in", "expired"].includes(status)) { try { await accessToken(); } catch { /* Son durum kilitli kalır; token veya ağ yanıtı renderer'a verilmez. */ } } return snapshot(); },
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    generation: () => epoch,
    isCurrent: current,
    requireSession: async () => { const generation = epoch; await accessToken(); if (!current(generation)) throw new Error("Muhakeme hesabına giriş gerekli."); return generation; },
    entitlement: async () => authorized("/api/lisans/v2/durum"),
    startTrial: async () => authorized("/api/lisans/v2/deneme", { urun: "rasathane", idempotency_key: crypto.randomUUID() }),
    serviceAccessToken: accessToken, // yalnız main; preload ve renderer'a açılmaz
    signOut: async () => { const token = session?.access_token; closePending(); clearSession(); let remoteRevoked = !token; try { if (token) { await api("/api/auth/device/revoke", {}, token); remoteRevoked = true; } } catch { /* yerel çıkış tamamlanır; ağ hatası token'ı diskte bırakmaz */ } return { signedOut: true, remoteRevoked }; },
  };
}
module.exports = { createAccount, validSession, pkcePair };

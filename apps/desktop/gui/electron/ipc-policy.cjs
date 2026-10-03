"use strict";

const JSON_ROUTES = new Map([
  ["/gui/health", ["GET"]], ["/gui/modeller", ["GET"]],
  ["/gui/kurulum", ["GET"]], ["/gui/kutuphane", ["GET"]],
  ["/gui/ayarlar", ["GET"]], ["/gui/ses_modeli_indir", ["POST"]],
  ["/gui/ollama_test", ["POST"]], ["/gui/klasor_ac", ["POST"]],
  ["/gui/dosya", ["GET"]],
  ["/api/rasathane/state", ["GET"]], ["/api/rasathane/analysis", ["POST"]],
  ["/api/rasathane/jobs", ["GET"]], ["/api/rasathane/workspaces", ["GET", "POST"]],
  ["/api/rasathane/conversations", ["GET"]],
  ["/api/rasathane/notes", ["GET", "POST"]], ["/api/rasathane/research", ["POST"]],
  ["/api/rasathane/topics", ["GET", "POST"]], ["/api/rasathane/library", ["GET"]],
  ["/api/rasathane/settings", ["GET", "POST"]], ["/api/rasathane/export", ["GET"]],
  ["/api/rasathane/sources", ["GET", "POST"]], ["/api/rasathane/articles", ["GET"]],
]);

function validateRequest(route, options = {}) {
  if (typeof route !== "string" || route.length > 4096 || !route.startsWith("/") || route.startsWith("//") || /[\\\x00-\x1f]/.test(route)) throw new Error("Geçersiz API yolu.");
  const url = new URL(route, "http://127.0.0.1");
  if (url.origin !== "http://127.0.0.1" || url.hash || url.username || url.password || url.pathname !== route.split("?")[0]) throw new Error("Geçersiz API yolu.");
  if (!options || typeof options !== "object" || Array.isArray(options)) throw new Error("Geçersiz istek.");
  if (Object.keys(options).some(key => !["method", "body"].includes(key))) throw new Error("İzin verilmeyen istek alanı.");
  const method = options.method || "GET";
  const methods = JSON_ROUTES.get(url.pathname) || (/^\/api\/rasathane\/(jobs|conversations)\/[a-zA-Z0-9_-]+$/.test(url.pathname) ? ["GET"] : /^\/api\/rasathane\/(articles\/[a-zA-Z0-9_-]+\/(summary|speech)|jobs\/[a-zA-Z0-9_-]+\/cancel|(topics|sources)\/[a-zA-Z0-9_-]+\/refresh)$/.test(url.pathname) ? ["POST"] : []);
  if (!methods.includes(method)) throw new Error("Bu API işlemi izinli değil.");
  if (method === "GET" && options.body !== undefined) throw new Error("GET gövdesi desteklenmiyor.");
  const body = options.body === undefined ? undefined : JSON.stringify(options.body);
  if (body !== undefined && Buffer.byteLength(body) > 32768) throw new Error("İstek gövdesi çok büyük.");
  if (url.pathname === "/gui/ollama_test") {
    const host = new URL(options.body?.host || "http://127.0.0.1:11434");
    if (host.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(host.hostname) || host.username || host.password) throw new Error("Model servisi bu bilgisayarda olmalı.");
  }
  return { route: url.pathname + url.search, method, body };
}

function trustedSender(event, window) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) return false;
  try { const url = new URL(event.senderFrame.url); return url.protocol === "rasathane:" && url.host === "app"; } catch { return false; }
}

function publicSourceURL(value) {
  if (typeof value !== "string" || value.length > 8192) throw new Error("Geçersiz kaynak bağlantısı.");
  const url = new URL(value);
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || (url.port && !["80", "443"].includes(url.port)) ||
      host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local") || !host.includes(".") ||
      /^(127\.|0\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.)/.test(host) || host.includes(":")) throw new Error("Yalnız kamuya açık web bağlantıları açılabilir.");
  return url.href;
}

module.exports = { validateRequest, trustedSender, publicSourceURL };

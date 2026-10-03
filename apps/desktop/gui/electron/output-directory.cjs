"use strict";
const fs = require("node:fs");
const path = require("node:path");

function resolveOutputDirectory({ configured, documents, desktop, userData }) {
  if (typeof configured === "string" && configured.trim()) return configured;
  const target = path.join(documents, "Rasathane");
  if (fs.existsSync(path.join(target, ".git"))) {
    throw new Error("Belgeler/Rasathane bir kaynak repo içeriyor. Ayarlardan ayrı bir çıktı klasörü seçin.");
  }
  const legacy = [path.join(userData, "workspace"), ...[
    "Rasathane  Gözlemevi", "Rasathane Gözlemevi", "RasathaneGözlemevi",
    "Rasathane Gözlemleri", "Youtube Analizleri",
  ].map(name => path.join(desktop, name))];
  for (const candidate of [target, ...legacy]) {
    if (!fs.existsSync(candidate)) continue;
    if (fs.lstatSync(candidate).isSymbolicLink()) {
      if (candidate === target) throw new Error("Rasathane çıktı klasörü bir bağlantı olamaz.");
      continue;
    }
    if (!fs.statSync(candidate).isDirectory() || fs.existsSync(path.join(candidate, ".git"))) continue;
    if (fs.readdirSync(candidate).length) return candidate;
  }
  return target;
}
module.exports = { resolveOutputDirectory };
